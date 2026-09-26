/**
 * Role Detail & Edit Page
 * View and edit role details, permissions, and assigned users
 */

"use client";

import { useState, useEffect } from "react";
import { useRouter, useParams } from "next/navigation";

interface RolePermission {
  id: number;
  resource_type: string;
  can_read: boolean;
  can_write: boolean;
  can_delete: boolean;
  can_approve: boolean;
  can_manage: boolean;
}

interface Role {
  id: number;
  name: string;
  display_name: string;
  description: string;
  discipline: string | null;
  color: string;
  is_system: boolean;
  is_active: boolean;
  created_by_id: number;
  created_at: string;
  updated_at: string;
  permissions: RolePermission[];
}

interface ResourceTypeInfo {
  code: string;
  display_name: string;
  description: string;
}

interface SystemInfo {
  resource_types: ResourceTypeInfo[];
  permission_actions: string[];
}

export default function RoleDetailPage() {
  const router = useRouter();
  const params = useParams();
  const roleId = params.id as string;

  const [role, setRole] = useState<Role | null>(null);
  const [systemInfo, setSystemInfo] = useState<SystemInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editMode, setEditMode] = useState(false);

  // Edit form state
  const [editData, setEditData] = useState({
    display_name: "",
    description: "",
    color: "",
    is_active: true,
  });

  // Permissions edit state
  const [permissionsMap, setPermissionsMap] = useState<
    Map<string, RolePermission>
  >(new Map());

  useEffect(() => {
    loadData();
  }, [roleId]);

  const loadData = async () => {
    try {
      setLoading(true);

      // Load system info
      const infoResponse = await fetch("/api/roles/system-info", {
        headers: {
          Authorization: `Bearer ${localStorage.getItem("ihp_access_token")}`,
        },
      });
      if (!infoResponse.ok) throw new Error("Failed to load system info");
      const info = await infoResponse.json();
      setSystemInfo(info);

      // Load role details
      const roleResponse = await fetch(`/api/roles/${roleId}`, {
        headers: {
          Authorization: `Bearer ${localStorage.getItem("ihp_access_token")}`,
        },
      });
      if (!roleResponse.ok) throw new Error("Failed to load role");
      const roleData = await roleResponse.json();
      setRole(roleData);

      // Initialize edit form
      setEditData({
        display_name: roleData.display_name,
        description: roleData.description,
        color: roleData.color,
        is_active: roleData.is_active,
      });

      // Initialize permissions map
      const permsMap = new Map<string, RolePermission>();
      roleData.permissions.forEach((p: RolePermission) => {
        permsMap.set(p.resource_type, p);
      });
      setPermissionsMap(permsMap);

      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "An error occurred");
    } finally {
      setLoading(false);
    }
  };

  const handleSaveBasicInfo = async () => {
    try {
      setSaving(true);

      const response = await fetch(`/api/roles/${roleId}`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${localStorage.getItem("ihp_access_token")}`,
        },
        body: JSON.stringify(editData),
      });

      if (!response.ok) throw new Error("Failed to update role");

      await loadData();
      setEditMode(false);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  };

  const handleUpdatePermission = async (
    resourceType: string,
    action: string,
    value: boolean
  ) => {
    const currentPerm = permissionsMap.get(resourceType) || {
      resource_type: resourceType,
      can_read: false,
      can_write: false,
      can_delete: false,
      can_approve: false,
      can_manage: false,
    };

    const updatedPerm = {
      ...currentPerm,
      [`can_${action}`]: value,
    };

    try {
      const response = await fetch(`/api/roles/${roleId}/permissions`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${localStorage.getItem("ihp_access_token")}`,
        },
        body: JSON.stringify({
          resource_type: resourceType,
          can_read: updatedPerm.can_read,
          can_write: updatedPerm.can_write,
          can_delete: updatedPerm.can_delete,
          can_approve: updatedPerm.can_approve,
          can_manage: updatedPerm.can_manage,
        }),
      });

      if (!response.ok) throw new Error("Failed to update permission");

      // Update local state
      const newMap = new Map(permissionsMap);
      newMap.set(resourceType, updatedPerm as RolePermission);
      setPermissionsMap(newMap);
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed to update permission");
    }
  };

  const handleDeleteRole = async () => {
    if (!role || role.is_system) return;

    if (
      !confirm(
        `Are you sure you want to delete the role "${role.display_name}"? This action cannot be undone.`
      )
    ) {
      return;
    }

    try {
      const response = await fetch(`/api/roles/${roleId}`, {
        method: "DELETE",
        headers: {
          Authorization: `Bearer ${localStorage.getItem("ihp_access_token")}`,
        },
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || "Failed to delete role");
      }

      router.push("/admin/roles");
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed to delete role");
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto"></div>
          <p className="mt-4 text-gray-600">Loading role...</p>
        </div>
      </div>
    );
  }

  if (error && !role) {
    return (
      <div className="p-8">
        <div className="bg-red-50 border border-red-200 rounded-lg p-4">
          <p className="text-red-800">Error: {error}</p>
          <button
            onClick={() => router.push("/admin/roles")}
            className="mt-2 text-red-600 hover:text-red-800 underline"
          >
            Back to Roles
          </button>
        </div>
      </div>
    );
  }

  if (!role) return null;

  return (
    <div className="max-w-7xl mx-auto p-8">
      {/* Header */}
      <div className="mb-8">
        <button
          onClick={() => router.push("/admin/roles")}
          className="text-blue-600 hover:text-blue-800 mb-4"
        >
          ← Back to Roles
        </button>

        <div className="flex items-start justify-between">
          <div className="flex items-center gap-4">
            <div
              className="w-8 h-8 rounded-lg"
              style={{ backgroundColor: role.color }}
            ></div>
            <div>
              <h1 className="text-3xl font-bold text-gray-900">
                {role.display_name}
              </h1>
              <p className="text-gray-500 text-sm">{role.name}</p>
            </div>
          </div>

          <div className="flex gap-2">
            {!role.is_system && !editMode && (
              <button
                onClick={() => setEditMode(true)}
                className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700"
              >
                Edit Role
              </button>
            )}
            {!role.is_system && (
              <button
                onClick={handleDeleteRole}
                className="px-4 py-2 bg-red-600 text-white rounded-md hover:bg-red-700"
              >
                Delete Role
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Basic Information */}
      <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 mb-6">
        <h2 className="text-xl font-semibold text-gray-900 mb-4">
          Basic Information
        </h2>

        {editMode ? (
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Display Name
              </label>
              <input
                type="text"
                value={editData.display_name}
                onChange={(e) =>
                  setEditData({ ...editData, display_name: e.target.value })
                }
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Description
              </label>
              <textarea
                value={editData.description}
                onChange={(e) =>
                  setEditData({ ...editData, description: e.target.value })
                }
                rows={3}
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Color
              </label>
              <input
                type="color"
                value={editData.color}
                onChange={(e) =>
                  setEditData({ ...editData, color: e.target.value })
                }
                className="h-10 w-20 rounded border border-gray-300"
              />
            </div>

            <div>
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={editData.is_active}
                  onChange={(e) =>
                    setEditData({ ...editData, is_active: e.target.checked })
                  }
                  className="rounded"
                />
                <span className="text-sm font-medium text-gray-700">
                  Active
                </span>
              </label>
            </div>

            <div className="flex gap-2">
              <button
                onClick={handleSaveBasicInfo}
                disabled={saving}
                className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-50"
              >
                {saving ? "Saving..." : "Save Changes"}
              </button>
              <button
                onClick={() => {
                  setEditMode(false);
                  setEditData({
                    display_name: role.display_name,
                    description: role.description,
                    color: role.color,
                    is_active: role.is_active,
                  });
                }}
                className="px-4 py-2 bg-gray-200 text-gray-700 rounded-md hover:bg-gray-300"
              >
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <div className="space-y-3">
            <div>
              <span className="text-sm font-medium text-gray-500">
                Description:
              </span>
              <p className="text-gray-900 mt-1">
                {role.description || "No description"}
              </p>
            </div>
            <div>
              <span className="text-sm font-medium text-gray-500">Type:</span>
              <span className="ml-2">
                {role.is_system ? (
                  <span className="inline-flex px-2 py-1 text-xs font-medium bg-purple-100 text-purple-800 rounded">
                    System Role
                  </span>
                ) : (
                  <span className="inline-flex px-2 py-1 text-xs font-medium bg-gray-100 text-gray-800 rounded">
                    Custom Role
                  </span>
                )}
              </span>
            </div>
            <div>
              <span className="text-sm font-medium text-gray-500">Status:</span>
              <span className="ml-2">
                {role.is_active ? (
                  <span className="inline-flex px-2 py-1 text-xs font-medium bg-green-100 text-green-800 rounded">
                    Active
                  </span>
                ) : (
                  <span className="inline-flex px-2 py-1 text-xs font-medium bg-red-100 text-red-800 rounded">
                    Inactive
                  </span>
                )}
              </span>
            </div>
          </div>
        )}
      </div>

      {/* Permissions Matrix */}
      <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
        <h2 className="text-xl font-semibold text-gray-900 mb-4">
          Permissions Matrix
        </h2>
        <p className="text-sm text-gray-600 mb-4">
          Configure what actions this role can perform on each resource type.
        </p>

        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                  Resource
                </th>
                <th className="px-6 py-3 text-center text-xs font-medium text-gray-500 uppercase">
                  Read
                </th>
                <th className="px-6 py-3 text-center text-xs font-medium text-gray-500 uppercase">
                  Write
                </th>
                <th className="px-6 py-3 text-center text-xs font-medium text-gray-500 uppercase">
                  Delete
                </th>
                <th className="px-6 py-3 text-center text-xs font-medium text-gray-500 uppercase">
                  Approve
                </th>
                <th className="px-6 py-3 text-center text-xs font-medium text-gray-500 uppercase">
                  Manage
                </th>
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-200">
              {systemInfo?.resource_types.map((resource) => {
                const perm = permissionsMap.get(resource.code);
                return (
                  <tr key={resource.code} className="hover:bg-gray-50">
                    <td className="px-6 py-4">
                      <div>
                        <div className="text-sm font-medium text-gray-900">
                          {resource.display_name}
                        </div>
                        <div className="text-xs text-gray-500">
                          {resource.description}
                        </div>
                      </div>
                    </td>
                    {["read", "write", "delete", "approve", "manage"].map(
                      (action) => (
                        <td key={action} className="px-6 py-4 text-center">
                          <input
                            type="checkbox"
                            checked={perm?.[`can_${action}` as keyof RolePermission] as boolean || false}
                            onChange={(e) =>
                              handleUpdatePermission(
                                resource.code,
                                action,
                                e.target.checked
                              )
                            }
                            disabled={role.is_system}
                            className="rounded text-blue-600 focus:ring-blue-500"
                          />
                        </td>
                      )
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {role.is_system && (
          <p className="mt-4 text-sm text-gray-500 italic">
            Note: System role permissions cannot be modified through the UI.
          </p>
        )}
      </div>
    </div>
  );
}
