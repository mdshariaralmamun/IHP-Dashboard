# IHP Automation System - Complete Workflow

## Overview
Automated system for KAUST In-House Projects (IHP) - from project initiation through document generation, 3D modeling, and submission.

---

## 1. Database Schema & SQL Insert Statements

Based on the PostgreSQL schema provided:

```sql
-- ============================================
-- 1. PROJECT METADATA INSERT
-- ============================================

INSERT INTO ihp_projects (
    pr_number,
    ear_number,
    title,
    building,
    level,
    area,
    room,
    description,
    status,
    project_type,
    created_by,
    approved_by,
    created_date,
    updated_date
) VALUES (
    '12579',                         -- PR Number
    '12519',                         -- EAR Number
    'Installation of in-house N2 line and back up power', -- Title
    'Building 3',                    -- Building
    'Level 0',                       -- Level
    'Area 4',                        -- Area
    'Room 3-0334',                   -- Room
    'CO2 Incubator N2 line - Installation of N2 gas line for laboratory equipment and backup power system', -- Description
    'Submitted for Approval',        -- Status
    'N2 Line Installation',          -- Project Type
    1,                               -- created_by (admin user ID)
    NULL,                            -- approved_by (pending)
    CURRENT_TIMESTAMP,               -- created_date
    CURRENT_TIMESTAMP                -- updated_date
);

-- ============================================
-- 2. SOW DATA INSERT
-- ============================================

INSERT INTO project_sow (
    project_id,
    content,
    sections,
    version
) VALUES (
    1,                               -- Assuming just-inserted project_id=1
    '<scope_of_work>...</scope_of_work>', -- Full SOW content (from sow_document.md)
    '{
        "introduction": "Project overview and intent",
        "scope_of_work": "Detailed breakdown by trade",
        "general_codes_standards": "KAUST compliance requirements",
        "documentation": "Submission requirements upon completion",
        "exclusions": "What is NOT included",
        "attachments": "References to BOQ, MTO, and drawings"
    }'::jsonb,
    1
);

-- ============================================
-- 3. BOQ DATA INSERT
-- ============================================

INSERT INTO project_boq (
    project_id,
    items,
    subtotal,
    vat,
    total,
    total_usd
) VALUES (
    1,
    '[
        {"item_no": "1", "description": "Copper N2 Piping - Interstitial Space (Above Ceiling)", "unit": "L.M.", "qty": "18", "unit_price": "125.00", "total": "2250.00"},
        {"item_no": "2", "description": "Valves - N2 Isolation (1/2" Ball Valves)", "unit": "EA", "qty": "2", "unit_price": "320.00", "total": "640.00"},
        {"item_no": "3", "description": "Fittings - 90° Elbows (1/2" Copper)", "unit": "EA", "qty": "4", "unit_price": "85.00", "total": "340.00"},
        {"item_no": "4", "description": "Fittings - 45° Elbows (1/2" Copper)", "unit": "EA", "qty": "5", "unit_price": "65.00", "total": "325.00"},
        {"item_no": "5", "description": "Dielectric Union (1/2")", "unit": "EA", "qty": "1", "unit_price": "180.00", "total": "180.00"},
        {"item_no": "6", "description": "POU Regulator (GCE Druva)", "unit": "EA", "qty": "1", "unit_price": "1200.00", "total": "1200.00"},
        {"item_no": "7", "description": "Pressure Gauge (0-15 PSI)", "unit": "EA", "qty": "1", "unit_price": "250.00", "total": "250.00"},
        {"item_no": "8", "description": "SS N2 Piping (Lab Area - Below Ceiling)", "unit": "L.M.", "qty": "3", "unit_price": "210.00", "total": "630.00"},
        {"item_no": "9", "description": "Swagelok Fittings (1/2")", "unit": "EA", "qty": "3", "unit_price": "95.00", "total": "285.00"},
        {"item_no": "10", "description": "Insulation - Pipe (Above Ceiling)", "unit": "L.M.", "qty": "21", "unit_price": "15.00", "total": "315.00"},
        {"item_no": "11", "description": "Insulation - Pipe (Below Ceiling)", "unit": "L.M.", "qty": "3.5", "unit_price": "18.00", "total": "63.00"},
        {"item_no": "12", "description": "Labeling / Tags (N2 - Yellow/Black)", "unit": "LOT", "qty": "1", "unit_price": "350.00", "total": "350.00"},
        {"item_no": "13", "description": "Stauff Clamps (1/2")", "unit": "EA", "qty": "7", "unit_price": "45.00", "total": "315.00"},
        {"item_no": "14", "description": "Supports - Screws (M8 x 30)", "unit": "EA", "qty": "28", "unit_price": "8.00", "total": "224.00"},
        {"item_no": "15", "description": "Channels (Galvanized)", "unit": "L.M.", "qty": "15", "unit_price": "32.00", "total": "480.00"},
        {"item_no": "16", "description": "Adaptors (1/2" to 1/4")", "unit": "EA", "qty": "1", "unit_price": "75.00", "total": "75.00"},
        {"item_no": "17", "description": "End Caps (1/2")", "unit": "EA", "qty": "1", "unit_price": "40.00", "total": "40.00"},
        {"item_no": "18", "description": "Wing Nuts (M8)", "unit": "BOX", "qty": "1", "unit_price": "55.00", "total": "55.00"},
        {"item_no": "19", "description": "Pressure Test - N2 System", "unit": "LOT", "qty": "1", "unit_price": "1500.00", "total": "1500.00"},
        {"item_no": "20", "description": "Purging & Purity Test", "unit": "LOT", "qty": "1", "unit_price": "800.00", "total": "800.00"},
        {"item_no": "21", "description": "Documentation & As-Builts", "unit": "LOT", "qty": "1", "unit_price": "650.00", "total": "650.00"}
    ]'::jsonb,
    11087.00,          -- subtotal (SAR)
    1663.05,           -- VAT 15% (SAR)
    12750.05,          -- total (SAR)
    3400.28            -- total (USD @ 3.75 SAR/USD)
);

-- ============================================
-- 4. MTO DATA INSERT
-- ============================================

INSERT INTO project_mto (
    project_id,
    items,
    created_date
) VALUES (
    1,
    '[
        {"item": "Copper Pipe 1/2" Type L", "quantity": 18, "unit": "LM"},
        {"item": "90° Elbow 1/2" Copper", "quantity": 4, "unit": "EA"},
        {"item": "45° Elbow 1/2" Copper", "quantity": 5, "unit": "EA"},
        {"item": "Dielectric Union 1/2""", "quantity": 1, "unit": "EA"},
        {"item": "Swagelok Connector 1/2"x1/4""", "quantity": 1, "unit": "EA"},
        {"item": "Swagelok Connector 1/2"x1/2""", "quantity": 1, "unit": "EA"},
        {"item": "GCE Druva POU Regulator", "quantity": 1, "unit": "EA"},
        {"item": "WIKA Pressure Gauge 0-15 PSI", "quantity": 1, "unit": "EA"},
        {"item": "Swagelok Ball Valve 1/2""", "quantity": 1, "unit": "EA"},
        {"item": "Insulation Copper 1/2""", "quantity": 18, "unit": "LM"},
        {"item": "Insulation SS 1/2""", "quantity": 3, "unit": "LM"},
        {"item": "N2 Labeling Tags", "quantity": 1, "unit": "LOT"},
        {"item": "Stauff Clamp 1/2""", "quantity": 7, "unit": "EA"},
        {"item": "Screw M8x30", "quantity": 28, "unit": "EA"},
        {"item": "Channel Galvanized LM", "quantity": 15, "unit": "LM"},
        {"item": "Adapter 1/2"x1/4""", "quantity": 1, "unit": "EA"},
        {"item": "End Cap 1/2""", "quantity": 1, "unit": "EA"},
        {"item": "Wing Nut M8", "quantity": 1, "unit": "BOX"}
    ]'::jsonb,
    CURRENT_TIMESTAMP
);

-- ============================================
-- 5. DRAWING DATA INSERT
-- ============================================

INSERT INTO project_drawing (
    project_id,
    model_data,
    schematic_url,
    iso_url,
    png_url
) VALUES (
    1,
    '{"copper_length": 18, "ss_length": 3, "elbows_90": 4, "elbows_45": 5, "valves": 4, "pipe_size": "1/2\""}',
    'schematic_n2_line_09se2026.png',
    'iso_n2_line_09se2026.png',
    'n3d_n2_line_09se2026.png'
);

-- ============================================
-- 6. APPROVAL WORKFLOW INSERT
-- ============================================

INSERT INTO project_approvals (
    project_id,
    step,
    approver_id,
    status,
    comments,
    created_date
) VALUES
    (1, 'Project Manager Review', 1, 'Pending', 'Initial submission review', CURRENT_TIMESTAMP),
    (1, 'QS Verify Quantities', 1, 'Pending', 'Quantity verification', CURRENT_TIMESTAMP),
    (1, 'HSE Officer - Safety Compliance', 1, 'Pending', 'HSE review', CURRENT_TIMESTAMP),
    (1, 'Quality Manager - Quality Compliance', 1, 'Pending', 'Quality check', CURRENT_TIMESTAMP),
    (1, 'Client (KAUST) - Final Approval', 1, 'Pending', 'Client approval awaited', CURRENT_TIMESTAMP);
```

---

## 2. Complete Automated Workflow

### Step 1: Project Initiation (Frontend Form)
```jsx
// ProjectCreationWizard.jsx
<WizardSteps>
  <Step1_BasicInfo
    projectTitle="Installation of in-house N2 line and back up power"
    prNumber="12579"
    earNumber="12519"
    location="Building 3, Level 0, Area 4, Room 3-0334"
    description="CO2 Incubator N2 line"
  />
  <Step2_ScopeDetails ... />
  <Step3_EquipmentSpecs ... />
  <Step4_ReviewSubmit onSubmit={handleSubmit} />
</WizardSteps>
```

### Step 2: Database Query (Historical Projects)
```sql
-- Fetch similar projects from Building 3, Area 4
SELECT pr_number, title, project_type, status, created_date
FROM ihp_projects
WHERE building = 'Building 3' AND area = 'Area 4'
ORDER BY created_date DESC
LIMIT 5;
```

### Step 3: AI Engine Integration
```javascript
// AI Service Calls
const generateSOW = async (projectData) => {
  const response = await fetch('/api/ai/generate-sow', {
    method: 'POST',
    body: JSON.stringify(projectData),
  });
  return response.json();
};

const generateMTO = async (scopeDescription) => {
  const response = await fetch('/api/ai/generate-mto', {
    method: 'POST',
    body: JSON.stringify({ scopeDescription }),
  });
  return response.json();
};

const generateBOQ = async (mtoData, historicalPricing) => {
  const response = await fetch('/api/ai/generate-boq', {
    method: 'POST',
    body: JSON.stringify({ mtoData, historicalPricing }),
  });
  return response.json();
};

const generatePipeForgePrompt = async (mtoData, location) => {
  const response = await fetch('/api/ai/generate-pipeforge-prompt', {
    method: 'POST',
    body: JSON.stringify({ mtoData, location }),
  });
  return response.json();
};
```

### Step 4: 3D Modeling (PipeForge)
```javascript
// PipeForge Integration
const build3DModel = async (pipeForgePrompt) => {
  const response = await fetch('/api/pipeforge/build', {
    method: 'POST',
    body: JSON.stringify(pipeForgePrompt),
  });
  return response.json(); // Returns all exports: 3D, views, PNG, ISO, MTO CSV
};
```

### Step 5: Quality Check
```javascript
// Quality Validation
const validateDocuments = async (sow, boq, mto, drawing) => {
  const issues = [];
  
  // Check pipe sizes match
  if (sow.pipeSizes !== boq.pipeSizes) issues.push('Pipe size mismatch');
  if (sow.pressureRating !== boq.pressureRating) issues.push('Pressure rating mismatch');
  if (sow.location !== boq.location) issues.push('Location mismatch');
  
  // Check quantities match
  if (mto.totalQuantity !== boq.totalQuantity) issues.push('Quantity mismatch');
  
  // Check for placeholder text
  if (sow.includes('TBD') || sow.includes('Insert')) issues.push('Placeholder text in SOW');
  if (boq.includes('Unit Price')) issues.push('Unit price placeholder in BOQ');
  
  return { isValid: issues.length === 0, issues };
};
```

### Step 5. Document Assembly (PDF)
```javascript
// PDF Generation Service
const assemblePDF = async (documents) => {
  const { generatePDF } = require('pdfkit');
  const doc = new PDFDocument();
  
  // Cover Page
  addCoverPage(doc, {
    title: 'Installation of in-house N2 line and back up power',
    prNumber: '12579',
    earNumber: '12519',
    location: 'Building 3, Level 0, Area 4, Room 3-0334',
    date: '2026-09-08'
  });
  
  // Table of Contents
  addTOCPage(doc);
  
  // SOW Section
  addSOWPage(doc, documents.sow);
  
  // BOQ Section
  addBOQPage(doc, documents.boq);
  
  // MTO Section
  addMTOPage(doc, documents.mto);
  
  // Drawing Section
  addDrawingPage(doc, documents.drawing);
  
  // Approval Page
  addApprovalPage(doc);
  
  return doc.end();
};
```

### Step 6: Procore Submission
```javascript
// Procore Upload
const submitToProcore = async (pdfBuffer, projectId) => {
  const formData = new FormData();
  formData.append('file', pdfBuffer, `N2_Line_Installation_${projectId}_${date}.pdf`);
  formData.append('project_id', projectId);
  formData.append('folder', 'Documents');
  
  const response = await fetch('/api/procore/upload', {
    method: 'POST',
    body: formData,
  });
  return response.json();
};

// Approval Workflow Trigger
const triggerApprovalWorkflow = async (projectId, step) => {
  const response = await fetch('/api/approvals/next-step', {
    method: 'POST',
    body: JSON.stringify({ projectId, step }),
  });
  return response.json();
};
```

### Step 7: Frontend Presentation
```jsx
// ProjectDashboard.jsx
<ProjectDashboard projectId={1} />
<DocumentViewer projectId={1} />
<ApprovalStatus projectId={1} />
<ExportButtons projectId={1} />
```

---

## 3. API Endpoints Summary

### Backend Routes (Node.js/Express)

```javascript
// Project Routes
router.post('/projects', createProject);           // Create new project
router.get('/projects/:id', getProject);           // Get project details
router.put('/projects/:id', updateProject);        // Update project
router.delete('/projects/:id', deleteProject);     // Delete project

// AI Generation Routes
router.post('/ai/generate-sow', generateSOW);      // Generate SOW document
router.post('/ai/generate-mto', generateMTO);      // Generate MTO
router.post('/ai/generate-boq', generateBOQ);      // Generate BOQ with pricing
router.post('/ai/generate-pipeforge-prompt', generatePipeForgePrompt); // PipeForge prompt

// 3D Modeling Routes
router.post('/pipeforge/build', build3DModel);     // Build 3D model

// Document Routes
router.post('/documents/assemble', assemblePDF);   // Assemble PDF
router.post('/documents/procore-upload', submitToProcore); // Procore upload

// Approval Routes
router.post('/approvals/next-step', triggerWorkflow); // Next approval step
router.get('/approvals/:projectId', getWorkflowStatus); // Get status

// Dashboard Routes
router.get('/dashboard/:projectId', getDashboard); // Project dashboard
```

---

## 4. Frontend Components

### Project Creation Wizard
```jsx
// src/components/wizard/ProjectCreationWizard.tsx
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { AiService } from '@/lib/ai-service';
import { PipeForgeService } from '@/lib/pipeforge';

export default function ProjectCreationWizard() {
  const [step, setStep] = useState(1);
  const { register, handleSubmit, values } = useForm();
  
  const onSubmit = async (data) => {
    // 1. Save to database
    await AiService.createProject(values);
    
    // 2. Generate SOW
    const sow = await AiService.generateSOW(values);
    
    // 3. Generate MTO
    const mto = await AiService.generateMTO(values.description);
    
    // 4. Generate BOQ
    const boq = await AiService.generateBOQ(mto, values.historicalPricing);
    
    // 5. Build 3D model
    const pipeforgeResult = await PipeForgeService.build3DModel({
      mtoData: mto,
      location: values.location,
    });
    
    // 6. Quality check
    const validation = await AiService.validateDocuments(sow, boq, mto, pipeforgeResult.drawing);
    
    // 7. Assemble PDF
    const pdf = await AiService.assemblePDF({
      sow,
      boq,
      mto,
      drawing: pipeforgeResult.drawing,
    });
    
    // 8. Submit to Procore
    await AiService.submitToProcore(pdf, values.projectId);
    
    // 9. Trigger approval workflow
    await AiService.triggerApprovalWorkflow(values.projectId, 'Project Manager Review');
    
    setStep(8); // Complete
  };
  
  return (
    <form onSubmit={handleSubmit(onSubmit)}>...</form>
  );
}
```

### Document Viewer
```jsx
// src/components/documents/DocumentViewer.tsx
import { useParams } from 'next/navigation';
import { useState } from 'react';

export default function DocumentViewer() {
  const { projectId } = useParams();
  const [activeTab, setActiveTab] = useState('sow');
  
  const tabs = [
    { label: 'SOW', component: <SOWViewer projectId={projectId} /> },
    { label: 'BOQ', component: <BOQViewer projectId={projectId} /> },
    { label: 'MTO', component: <MTOViewer projectId={projectId} /> },
    { label: 'Drawing', component: <DrawingViewer projectId={projectId} /> },
  ];
  
  return (
    <div className="tabs">
      {tabs.map(tab => (
        <Tab key={tab.label} label={tab.label} active={activeTab === tab.label} onClick={() => setActiveTab(tab.label)} />
      ))}
      <div className="content">
        {tabs.find(t => t.label === activeTab)?.component}
      </div>
    </div>
  );
}
```

### 3D Viewer
```jsx
// src/components/3d/PipeForgeViewer.tsx
import { useEffect, useState } from 'react';

export default function PipeForgeViewer({ projectId }) {
  const [views, setViews] = useState({
    threeD: '',
    iso: '',
    top: '',
    front: '',
    side: '',
    png: '',
    schematic: '',
  });
  
  useEffect(() => {
    // Fetch 3D views from backend
    fetch(`/api/pipeforge/views?projectId=${projectId}`)
      .then(res => res.json())
      .then(setViews)
      .catch(console.error);
  }, [projectId]);
  
  return (
    <div className="pipe-forge-viewer">
      <Canvas>
        <ThreeDView src={views.threeD} />
        <IsoView src={views.iso} />
        <TopView src={views.top} />
        <FrontView src={views.front} />
        <SideView src={views.side} />
      </Canvas>
      <ExportButtons views={views} />
    </div>
  );
}
```

---

## 5. Workflow Automation Flowchart

```
┌─────────────────────────────────────────────────────────────────┐
│  PROJECT INITIATION                                                    │
│  └── User fills multi-step form → Saves to DB                        │
│         │                                                            │
│         ▼                                                            │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │  AI DOCUMENT GENERATION                                         │ │
│  │  ├── generateSOW() → sow_document.md                            │ │
│  │  ├── generateMTO() → mto_document.md                            │ │
│  │  ├── generateBOQ() → boq_document.md                            │ │
│  │  └── generatePipeForgePrompt() → pipeforge_prompt.md            │ │
│  └─────────────────────────────────────────────────────────────┘ │
│         │                                                            │
│         ▼                                                            │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │  3D MODELING (PipeForge)                                         │ │
│  │  ├── Build 3D model from MTO                                     │ │
│  │  ├── Render views (3D, Iso, Top, Front, Side)                   │ │
│  │  ├── Export PNG, Schematic, Iso sheet                           │ │
│  │  └── Generate MTO CSV (verified against model)                 │ │
│  └─────────────────────────────────────────────────────────────┘ │
│         │                                                            │
│         ▼                                                            │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │  QUALITY CHECK                                                     │ │
│  │  ├── validateDocuments(sow, boq, mto, drawing)                 │ │
│  │  ├── Check pipe sizes match                                      │ │
│  │  ├── Check quantities match                                      │ │
│  │  ├── Check no placeholder text                                   │ │
│  │  └── Flag inconsistencies for correction                         │ │
│  └─────────────────────────────────────────────────────────────┘ │
│         │                                                            │
│         ▼                                                            │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │  DOCUMENT ASSEMBLY (PDF)                                           │ │
│  │  ├── Cover page (title, PR#, EAR#, location, date)              │ │
│  │  ├── Table of Contents                                            │ │
│  │  ├── SOW section (pages 1-2)                                     │ │
│  │  ├── BOQ section (pages 3-5)                                     │ │
│  │  ├── MTO section (pages 5-6)                                     │ │
│  │  ├── Drawing section (page 7)                                    │ │
│  │  └── Approval page                                                │ │
│  └─────────────────────────────────────────────────────────────┘ │
│         │                                                            │
│         ▼                                                            │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │  PROCORE SUBMISSION                                                │ │
│  │  ├── Upload PDF to Procore                                        │ │
│  │  ├── Trigger approval workflow (5 steps)                         │ │
│  │  ├── PM Review → QS Verify → HSE Check → QA Check → Client Approval│ │
│  │  └── Update project status in DB                                  │ │
│  └─────────────────────────────────────────────────────────────┘ │
│         │                                                            │
│         ▼                                                            │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │  FRONTEND PRESENTATION                                             │ │
│  │  ├── Project dashboard with status                               │ │
│  │  ├── Document previews (SOW, BOQ, MTO, Drawing)                 │ │
│  │  ├── Approval status tracking                                    │ │
│  │  └── Export/download all documents                               │ │
│  └─────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

---

## 6. Setup Commands (Complete)

### Frontend Setup
```bash
npx create-next-app@latest ihp-frontend
cd ihp-frontend
npm install @mui/material @emotion/react @emotion/styled
npm install axios react-hook-form
npm install @types/pdfjs-dist  // For document viewing
```

### Backend Setup
```bash
mkdir ihp-backend
cd ihp-backend
npm init -y
npm install express cors dotenv pg jsonwebtoken
npm install openai          // AI integration
npm install pdfkit          // PDF generation
npm install pg              // PostgreSQL client
npm install morgan          // HTTP request logging
```

### Database Setup
```bash
# Create database
createdb ihp_projects

# Apply schema (run the SQL from Section 1)
psql -d ihp_projects -f schema.sql

# Enable extensions if needed
psql -d ihp_projects -c "CREATE EXTENSION IF NOT EXISTS jsonb_path_ops;"
```

### AI Service Configuration
```env
# .env file
OPENAI_API_KEY=sk-your-openai-key-here
DATABASE_URL=postgresql://postgres:password@localhost:5432/ihp_projects
NEXT_PUBLIC_API_URL=http://localhost:8001/api
PIPEFORGE_API_KEY=your-pipeforge-key-here
```

### Run Development Servers
```bash
# Frontend
cd ihp-frontend
npm run dev          # Runs on http://localhost:3000

# Backend  
cd ihp-backend
npm run dev          # Runs on http://localhost:8001 (uvicorn app.main:app)
```

---

## 7. Quick Start - End-to-End Test

```bash
# 1. Start both servers
# 2. Visit http://localhost:3000
# 3. Click "Create New Project"
# 4. Fill form:
#    - Project Title: "Installation of in-house N2 line and back up power"
#    - PR #: "12579"
#    - EAR #: "12519"
#    - Location: "Building 3, Level 0, Area 4, Room 3-0334"
#    - Description: "CO2 Incubator N2 line"
# 5. Submit
# 6. Watch console for automation progress:
#    - SOW generation ✓
# - MTO generation ✓
# - BOQ generation ✓
# - PipeForge 3D model ✓
# - Quality check ✓
# - PDF assembly ✓
# - Procore submission ✓
# - Approval workflow started ✓
# 7. View project dashboard at /projects/1
```

---

## 8. KAUST Branding & Standards

All generated documents apply:
- **KAUST Green:** #006A4E (primary)
- **KAUST Blue:** #003D70 (secondary)
- **KAUST Sand:** #B7995D (accent)
- **Font:** Arial 11pt consistent
- **Page numbers:** Page X of Y
- **Watermark:** "DRAFT" if not final approved
- **Header/footer:** KAUST Engineering Department standard
- **Cover page:** KAUST logo, project info, revision table

---

## 9. Error Handling & Fallbacks

### AI Generation Failures
```javascript
// If AI fails, use template fallback
const fallbackSOW = ` 
  <h2>Scope of Work: ${project.title}</h2>
  <p>SOW generation in progress. Please check back shortly.</p>
`;
```

### PipeForge Model Failures
```javascript
// If PipeForge API fails, generate basic SVG model
const basicSvgModel = `<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600">
  <!-- Basic copper + SS pipe layout -->
  <line x1="0" y1="0" x2="800" y2="0" stroke="silver" stroke-width="5"/> <!-- Copper run -->
  <line x1="790" y1="0" x2="790" y2="-300" stroke="steelblue" stroke-width="5"/> <!-- SS drop -->
  <circle cx="0" cy="0" r="10" fill="silver"/> <!-- Ball valve -->
  <circle cx="790" cy="-300" r="10" fill="steelblue"/> <!-- Regulator -->
  <text x="20" y="20">N2 Line Installation</text>
</svg>`;
```

### Database Connection Failures
```javascript
// Retry logic with exponential backoff
const retryDbOperation = async (operation, maxRetries = 3) => {
  for (let i = 0; i < maxRetries; i++) {
    try {
      return await operation();
    } catch (error) {
      if (i === maxRetries - 1) throw error;
      await new Promise(resolve => setTimeout(resolve, 1000 * (i + 1)));
    }
  }
};
```

---

## 10. Security & Permissions

### User Roles & Capabilities
- **admin:** Full access - all stages, all capabilities
- **engineering:** MOM, EAR, SOW, BOQ generation
- **procurement:** BOQ review, vendor management
- **construction:** 3D model viewing, construction tracking
- **facilities:** Closeout, warranties, maintenance
- **qa:** Document validation, quality checks

### API Rate Limiting
```javascript
// Express rate limiting example
const limiter = rateLimit({
  windowMs: 15 * 60 * 1000, // 15 minutes
  max: 100 // limit each IP to 100 requests per windowMs
});
app.use('/api/', limiter);
```

### Data Validation
```javascript
// Zod schema examples for input validation
const projectSchema = z.object({
  prNumber: z.string().min(1).regex(/^PR-\d{4}$/),
  earNumber: z.string().regex(/^EAR-\d{4}$/),
  title: z.string().min(5),
  building: z.string().min(1),
  level: z.string().min(1),
  area: z.string().min(1),
  room: z.string().min(1),
  description: z.string().min(10),
});
```

---

## 11. Future Enhancements

### Phase 2 (Q4 2026)
- Integration with KAUST ERP system
- Automated vendor RFQ generation from BOQ
- Real-time material price tracking
- BIM (Building Information Modeling) integration

### Phase 3 (2027)
- Generative AI for cost optimization
- Digital twin integration with as-built models
- Mobile app for field verification
- Blockchain-based approval tracking

### Phase 4 (2028)
- Multi-project dashboard with portfolio analytics
- AI-powered risk assessment
- Automated compliance checking against evolving KAUST standards
- Integration with external procurement systems

---

*IHP Automation System v1.0*  
*Generated: 2026-09-08*  
*KAUST In-House Projects Delivery Platform*