import type { ProjectSummary, AuditEntry } from '@/lib/types';
import { useMemo, useState } from 'react';

const STAGES = [
  { id: 'INTAKE', label: 'Intake' },
  { id: 'MOM', label: 'MOM' },
  { id: 'EAR', label: 'EAR' },
  { id: 'DESIGN', label: 'Design' },
  { id: 'PROCORE', label: 'Procore' },
  { id: 'MTO_PTW', label: 'MTO & PTW' },
  { id: 'CONSTRUCTION', label: 'Construction' },
  { id: 'SHUTDOWN', label: 'Shutdown' },
  { id: 'INSPECTION', label: 'Inspection' },
  { id: 'WCC_WCH', label: 'WCC / WCH' },
  { id: 'PUNCH_LIST', label: 'Punch List' },
  { id: 'TECH_LIBRARY', label: 'Tech Library' },
];

export default function TrackerStepper({ project, audit = [] }: { project: ProjectSummary, audit?: AuditEntry[] }) {
  const currentStage = project.stage;
  
  // Map backend stages to the visual tracker index
  let currentIndex = 0;
  if (currentStage === 'INTAKE') currentIndex = 0;
  else if (currentStage.startsWith('MOM_') || currentStage === 'DISPOSITION') currentIndex = 1;
  else if (currentStage.startsWith('EAR_')) currentIndex = 2;
  else if (currentStage.startsWith('SOW_')) currentIndex = 3;
  else if (currentStage === 'PROCUREMENT') currentIndex = 4;
  else if (currentStage.startsWith('MTO_') || currentStage === 'WORK_PERMIT') currentIndex = 5;
  else if (currentStage === 'CONSTRUCTION') currentIndex = 6;
  else if (currentStage === 'SHUTDOWN') currentIndex = 7;
  else if (currentStage === 'QUALITY_INSPECTION') currentIndex = 8;
  else if (currentStage === 'CLOSEOUT') currentIndex = 9;
  else if (currentStage === 'PUNCH_LIST') currentIndex = 10;
  else if (currentStage === 'TECH_LIBRARY') currentIndex = 11;
  else if (currentStage === 'ICR_DONE') currentIndex = 11;

  // Map audit log to stage times (very naive matching by taking the first audit action mentioning the stage)
  const stageDetails = useMemo(() => {
    const map: Record<number, { date: string, time: string, justification: string }> = {};
    
    // Sort audit oldest first to find the first time it entered a stage
    const sortedAudit = [...audit].sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime());
    
    // We will just do a rough matching of audit actions to index
    sortedAudit.forEach(entry => {
      let matchedIndex = -1;
      const action = entry.action.toLowerCase();
      const detailStr = JSON.stringify(entry.detail).toLowerCase();
      
      if (action.includes('create')) matchedIndex = 0;
      else if (action.includes('mom') || detailStr.includes('mom_confirmed')) matchedIndex = 1;
      else if (action.includes('ear') || detailStr.includes('ear_approved')) matchedIndex = 2;
      else if (action.includes('sow') || detailStr.includes('sow_approved')) matchedIndex = 3;
      else if (action.includes('mto') || action.includes('permit')) matchedIndex = 5;
      else if (detailStr.includes('construction')) matchedIndex = 6;
      else if (action.includes('closeout')) matchedIndex = 9;
      else if (action.includes('promote_to_ear')) matchedIndex = 2;
      
      if (matchedIndex !== -1 && !map[matchedIndex]) {
        const d = new Date(entry.created_at);
        let justification = String(entry.detail?.reason ?? entry.detail?.comments ?? '');
        
        map[matchedIndex] = {
          date: d.toLocaleDateString(),
          time: d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
          justification: justification
        };
      }
    });
    
    // For index 0 (Intake), if no audit, use project created_at
    if (!map[0] && project.created_at) {
      const d = new Date(project.created_at);
      map[0] = { date: d.toLocaleDateString(), time: d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }), justification: '' };
    }
    
    return map;
  }, [audit, project.created_at]);

  const [expandedIndex, setExpandedIndex] = useState<number | null>(null);

  return (
    <div className="py-6 w-full overflow-x-auto">
      <div className="flex min-w-[1000px]">
        {STAGES.map((stage, index) => {
          const isCompleted = index < currentIndex;
          const isCurrent = index === currentIndex;
          const isFuture = index > currentIndex;
          
          let bgColor = 'bg-apple-border text-apple-muted';
          if (isCompleted) bgColor = 'bg-green-500 text-white';
          else if (isCurrent) bgColor = 'bg-blue-600 text-white';
          
          const details = stageDetails[index];

          // Chevron polygon math:
          let clipPath = 'polygon(0 0, calc(100% - 20px) 0, 100% 50%, calc(100% - 20px) 100%, 0 100%, 20px 50%)';
          if (index === 0) clipPath = 'polygon(0 0, calc(100% - 20px) 0, 100% 50%, calc(100% - 20px) 100%, 0 100%)';
          if (index === STAGES.length - 1) clipPath = 'polygon(0 0, 100% 0, 100% 100%, 0 100%, 20px 50%)';

          return (
            <div key={stage.id} className="relative flex-1 flex flex-col group cursor-pointer" onClick={() => setExpandedIndex(expandedIndex === index ? null : index)}>
              <div 
                className={`relative h-14 flex items-center justify-center transition-all ${bgColor} ${isCurrent ? 'animate-pulse shadow-inner' : ''}`}
                style={{
                  clipPath,
                  marginLeft: index === 0 ? '0' : '-18px',
                  zIndex: STAGES.length - index,
                  paddingLeft: index === 0 ? '10px' : '25px',
                  paddingRight: index === STAGES.length - 1 ? '10px' : '25px',
                }}
              >
                <div className="flex flex-col items-center">
                  <span className="text-xs font-bold whitespace-nowrap">{stage.label}</span>
                  {(details || isCurrent) && (
                    <span className="text-[10px] mt-0.5 opacity-90 whitespace-nowrap">
                      {details ? details.date : 'In Progress'}
                    </span>
                  )}
                </div>
              </div>
              
              {/* Expanding Details Section Below */}
              <div className={`transition-all overflow-hidden absolute top-16 left-0 right-0 z-50 px-2 ${expandedIndex === index ? 'max-h-40 opacity-100' : 'max-h-0 opacity-0 pointer-events-none'}`}>
                <div className="bg-apple-surface border border-apple-border shadow-md rounded-md p-3 text-xs w-48 -ml-8 relative">
                  <div className="absolute -top-2 left-1/2 -translate-x-1/2 w-4 h-4 bg-apple-surface border-t border-l border-apple-border transform rotate-45"></div>
                  <div className="relative z-10">
                    <p className="font-bold text-apple-text mb-1">{stage.label}</p>
                    {details ? (
                      <>
                        <p className="text-apple-muted"><strong>Date:</strong> {details.date}</p>
                        <p className="text-apple-muted"><strong>Time:</strong> {details.time}</p>
                        {details.justification && (
                          <p className="text-apple-muted mt-1 line-clamp-3"><strong>Detail:</strong> {details.justification}</p>
                        )}
                      </>
                    ) : (
                      <p className="text-apple-muted italic">{isFuture ? 'Not started yet.' : 'In progress...'}</p>
                    )}
                  </div>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

