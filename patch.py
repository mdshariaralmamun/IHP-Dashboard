import sys

file_path = 'frontend/src/app/projects/[id]/page.tsx'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Imports
content = content.replace(
    "import SowBoqPanel from '@/components/project/SowBoqPanel';",
    "import SowBoqPanel from '@/components/project/SowBoqPanel';\nimport PromoteToEarModal from '@/components/project/PromoteToEarModal';\nimport TrackerStepper from '@/components/TrackerStepper';"
)

# 2. State
content = content.replace(
    "const [activeTab, setActiveTab] = useState<TabKey>('all');",
    "const [activeTab, setActiveTab] = useState<TabKey>('all');\n  const [showPromoteModal, setShowPromoteModal] = useState(false);"
)

# 3. EAR tag
button_logic = '''                <span className="text-xs font-bold text-slate-400 uppercase tracking-widest">{project.pr_number}</span>
                {project.ear_number && (
                  <span className="ml-3 text-xs font-bold text-blue-500 uppercase tracking-widest border border-blue-200 bg-blue-50 px-2 py-0.5 rounded">
                    EAR: {project.ear_number}
                  </span>
                )}
                <h1'''
content = content.replace('                <span className="text-xs font-bold text-slate-400 uppercase tracking-widest">{project.pr_number}</span>\n                <h1', button_logic, 1)

# 4. Button
button_code = '''                {project.disposition && (
                  <span className="rounded-full bg-slate-900 px-3 py-1 text-xs font-bold text-white">
                    {project.disposition}
                  </span>
                )}
                {canDo(user, 'projects.edit') && !project.ear_number && (
                  <button
                    type="button"
                    onClick={() => setShowPromoteModal(true)}
                    className="rounded border border-blue-200 bg-blue-50 px-3 py-1.5 text-xs font-medium text-blue-700 hover:bg-blue-100"
                  >
                    Promote to EAR (Assign New PR)
                  </button>
                )}'''
content = content.replace('''                {project.disposition && (
                  <span className="rounded-full bg-slate-900 px-3 py-1 text-xs font-bold text-white">
                    {project.disposition}
                  </span>
                )}''', button_code, 1)


# 5. Live Tracking block
live_tracking = '''            {/* Stage Stepper Tabs */}
            {(activeTab === 'all') && (
              <div className="bg-white p-6 rounded-lg shadow-sm border border-slate-200 mb-6">
                <h3 className="text-base font-bold text-slate-800 mb-4">Live Tracking</h3>
                <TrackerStepper project={project} audit={audit} />
                
                <div className="mt-6 p-4 bg-slate-50 border border-slate-200 rounded-md">
                  <h4 className="text-sm font-semibold text-slate-700 mb-1">Public Tracking Link</h4>
                  <p className="text-xs text-slate-500 mb-2">Share this link with the PI or external stakeholders so they can track the project without logging in.</p>
                  <div className="flex items-center gap-2">
                    <input 
                      type="text" 
                      readOnly 
                      value={`${typeof window !== 'undefined' ? window.location.origin : ''}/track/${project.tracking_token}`}
                      className="flex-1 text-sm bg-white border border-slate-300 rounded px-3 py-2 text-slate-600 focus:outline-none"
                    />
                    <button 
                      type="button"
                      onClick={() => navigator.clipboard.writeText(`${window.location.origin}/track/${project.tracking_token}`)}
                      className="px-4 py-2 bg-slate-200 hover:bg-slate-300 text-slate-700 text-sm font-medium rounded transition-colors"
                    >
                      Copy
                    </button>
                  </div>
                </div>
                
                <div className="mt-4 bg-blue-50/50 p-3 rounded text-xs text-blue-800 border border-blue-100 flex gap-2 items-start">
                  <span className="text-lg">💡</span>
                  <div>
                    <strong>Data Sources Connected:</strong> This tracking table consolidates information from the O&amp;M Project Progress Tracking Sheet, IHP Construction Projects, PR Requests, and the Planner, providing a single unified view.
                  </div>
                </div>
              </div>
            )}
            
            <div className="flex overflow-x-auto rounded-lg border border-slate-200 bg-white p-1 shadow-2xs gap-1">'''

content = content.replace('''            {/* Stage Stepper Tabs */}
            <div className="flex overflow-x-auto rounded-lg border border-slate-200 bg-white p-1 shadow-2xs gap-1">''', live_tracking, 1)

# 6. Modal
modal = '''        )}

        {showPromoteModal && (
          <PromoteToEarModal 
            projectId={project!.id} 
            onClose={() => setShowPromoteModal(false)}
            onSuccess={() => {
              setShowPromoteModal(false);
              void load();
            }}
          />
        )}
      </main>'''

content = content.replace('''        )}
      </main>''', modal, 1)

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
