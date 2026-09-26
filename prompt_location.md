# AI Prompt Storage Location

The AI prompts for the IHP Automation System are stored at:
- **Path:** `E:\ENGINEERING_DATA\prompt AI`
- **Purpose:** Historical and template prompts for document generation

**Referenced Prompts:**
1. SOW generation prompt - used for Scope of Work creation from project details
2. MTO generation prompt - used for Material Take-Off calculation from scope
3. BOQ generation prompt - used for Bill of Quantities with pricing from MTO
4. PipeForge prompt - used for 3D model generation from MTO data
5. Quality check prompt - used for cross-document consistency validation

**Prompt Organization:**
The directory likely contains subfolders or files named by document type:
- `SOW/` - Scope of Work prompts
- `MTO/` - Material Take-Off prompts  
- `BOQ/` - Bill of Quantities prompts
- `PipeForge/` - 3D modeling prompts
- `QC/` - Quality control prompts

**Usage in Automation System:**
- The `automation_system.md` references these prompts for the AI engine integration
- Backend endpoints `/api/ai/generate-sow`, `/api/ai/generate-mto`, etc. load prompts from this location
- Prompts are templatized with project-specific data substituted at runtime
- Historical project data from Building 3, Area 4 is used as context for prompt generation

**Next Steps:**
- Review prompts at `E:\ENGINEERING_DATA\prompt AI` to ensure compatibility with new automation system
- Update prompt templates to match the new IHP project schema
- Ensure version control for prompt changes
- Document prompt revision history

---
*Last verified: 2026-09-08*
*Storage path: E:\ENGINEERING_DATA\prompt AI*