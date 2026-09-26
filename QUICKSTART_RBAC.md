# 🚀 Quick Start Guide - RBAC Enhanced System

## ⚠️ Important Fixes Applied

The following critical fixes have been applied to resolve the 500 error:

1. ✅ Added RBAC models import to `app/main.py`
2. ✅ Updated `app/api/__init__.py` to export RBAC routers
3. ✅ Updated `app/services/__init__.py` to export RBAC service

## 🎯 Option 1: Automated Startup (Recommended)

Simply double-click this file:
```
start-with-rbac.bat
```

This will:
1. Run database migrations
2. Seed RBAC roles and permissions
3. Install frontend dependencies (if needed)
4. Start both backend and frontend servers
5. Open the application in your browser

## 🎯 Option 2: Manual Startup

### Step 1: Open PowerShell or CMD in project directory

```powershell
cd "C:\Users\MOHAMMED MAMUN\IHP Design and Construction"
```

### Step 2: Run Database Migration

```powershell
cd backend
.venv\Scripts\python.exe -m alembic upgrade head
```

Expected output: `Running upgrade ... -> 20260917_2055_add_rbac_tables`

### Step 3: Seed RBAC Roles (First time only)

```powershell
.venv\Scripts\python.exe -m app.scripts.seed_rbac_roles
```

Expected output: Shows creation of system roles and discipline roles

### Step 4: Start Backend Server

```powershell
.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8001
```

Keep this window open. Expected output: `Application startup complete.`

### Step 5: Start Frontend Server (New Terminal)

```powershell
cd frontend
npm run dev
```

Expected output: `Ready on http://localhost:3000`

### Step 6: Open Browser

Navigate to: **http://localhost:3000/login**

## 🔐 Login Credentials

Check your `.env` file for:
- **Username**: Value of `ADMIN_USERNAME`
- **Password**: Value of `ADMIN_PASSWORD`

## 🎨 RBAC Admin Pages

After logging in, access:

1. **Roles Management**: http://localhost:3000/admin/roles
   - View all roles
   - Create custom roles
   - Edit permissions matrix
   
2. **User-Role Management**: http://localhost:3000/admin/users-roles
   - Assign roles to users
   - Set primary roles
   - Manage user access

3. **API Documentation**: http://localhost:8001/docs
   - Interactive API explorer
   - Test RBAC endpoints

## 🔍 Verify RBAC System is Working

### Check 1: API Health
```
http://localhost:8001/api/health
```
Should return: `{"status": "ok"}`

### Check 2: System Info
```
http://localhost:8001/api/roles/system-info
```
Should return disciplines and resource types

### Check 3: List Roles
```
http://localhost:8001/api/roles/
```
Should return array of roles (admin, planning, etc.)

## ❌ Troubleshooting

### Error: "Migration failed"
**Solution**: The migration may already be applied. Check with:
```powershell
cd backend
.venv\Scripts\python.exe -m alembic current
```

### Error: "Seed script failed"
**Solution**: Roles may already exist. This is safe to ignore if you see "already exists" messages.

### Error: "Port 8001 already in use"
**Solution**: 
1. Find process: `netstat -ano | findstr :8001`
2. Kill process: `taskkill /PID <pid> /F`

### Error: "Port 3000 already in use"
**Solution**:
1. Find process: `netstat -ano | findstr :3000`
2. Kill process: `taskkill /PID <pid> /F`

### Error: "Module not found"
**Solution**: Backend dependencies missing
```powershell
cd backend
.venv\Scripts\pip install -e .
```

### Error: "npm: command not found"
**Solution**: Frontend dependencies missing
```powershell
cd frontend
npm install
```

### Still Getting 500 Error?

1. **Check backend logs** in the terminal where uvicorn is running
2. **Check for Python errors** - look for import errors or syntax errors
3. **Verify virtual environment** is activated (you should see `.venv` in prompt)
4. **Clear Python cache**:
   ```powershell
   cd backend
   Remove-Item -Recurse -Force app\__pycache__
   Remove-Item -Recurse -Force app\api\__pycache__
   Remove-Item -Recurse -Force app\services\__pycache__
   ```
5. **Restart servers** after clearing cache

## 📊 Default Roles Created

After seeding, these roles will be available:

### System Roles (Cannot be deleted)
- **Administrator** - Full system access
- **Planning/Planner** - Disposition, EAR, SOW, BOQ management
- **Construction Manager** - Construction, work permits, closeout
- **Trade Engineer** - Technical discipline input
- **Team Member** - Read-only + meeting participation

### Discipline Roles (Can be customized)
- Civil/Architectural Engineer
- Electrical Engineer
- Plumbing/Gas Piping Engineer
- HVAC Engineer
- Low Current Engineer
- Fire Protection Engineer
- Document Controller
- Safety Officer
- Project Control
- Procurement Department
- Site Supervisor
- Technician
- Labor
- QA/QC Engineer

## 🎯 Next Steps

1. **Log in** with admin credentials
2. **Navigate to** http://localhost:3000/admin/roles
3. **Review** the created roles and their permissions
4. **Assign roles** to users via http://localhost:3000/admin/users-roles
5. **Test permissions** by logging in as different users

## 📝 Notes

- Backend runs on **port 8001** (not 8000, as mentioned in README)
- Frontend runs on **port 3000**
- Database file: `backend/dev.db` (SQLite for development)
- All RBAC data is stored in the database
- System roles cannot be deleted but can be viewed

## 🆘 Need Help?

Check the comprehensive documentation:
- **RBAC Implementation**: `docs/RBAC_IMPLEMENTATION.md`
- **Project README**: `README.md`

---

**Last Updated**: 2026-09-17  
**Status**: ✅ Ready to run
