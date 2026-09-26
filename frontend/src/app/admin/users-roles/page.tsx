/**
 * User Management Page with Role Assignment
 * Admin interface for managing users and their role assignments
 */

"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";

interface Role {
  id: number;
  name: string;
  display_name: string;
  discipline: string | null;
  color: string;
  is_system: boolean;
  is_active: boolean;
  permission_count: number;
  user_count: number;
}

interface User {
  id: number;
  username: string;
  full_name: string;
  title: string;
  email: string;
  is_active: boolean;
  roles?: Role[];
  primary_role?: Role | null;
}

export default function UsersManagementPage() {
  const router = useRouter();
  const [users, setUsers] = useState<User[]>([]);
  const [roles, setRoles] = useState<Role[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedUser, setSelectedUser] = useState<User | null>(null);
  const [showRoleAssignModal, setShowRoleAssignModal] = useState(false);
  const [assigningRoles, setAssigningRoles] = useState<number[]>([]);
  const [primaryRoleId, setPrimaryRoleId] = useState<number | null>(null);

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    try {
      setLoading(true);

      // Load users
      const usersResponse = await fetch("/api/admin/users", {
        headers: {
          Authorization: `Bearer ${localStorage.getItem("ihp_access_token")}`,
        },
      });

      if (!usersResponse.ok) throw new Error("Failed to load users");
      const usersData = await usersResponse.json();

      // Load roles
      const rolesResponse = await fetch("/api/roles", {
        headers: {
          Authorization: `Bearer ${localStorage.getItem("ihp_access_token")}`,
        },
      });

      if (!rolesResponse.ok) throw new Error("Failed to load roles");
      const rolesData = await rolesResponse.json();

      setUsers(usersData);
      setRoles(rolesData);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "An error occurred");
    } finally {
      setLoading(false);
    }
  };

  const loadUserRoles = async (userId: number) => {
    try {
      const response = await fetch(`/api/user-roles/user/${userId}`, {
        headers: {
          Authorization: `Bearer ${localStorage.getItem("ihp_access_token")}`,
        },
      });

      if (!response.ok) throw new Error("Failed to load user roles");
      const userData = await response.json();

      setSelectedUser(userData);
      setAssigningRoles(userData.roles.map((r: Role) => r.id));
      setPrimaryRoleId(userData.primary_role?.id || null);
      setShowRoleAssignModal(true);
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed to load user roles");
    }
  };

  const handleAssignRoles = async () => {
    if (!selectedUser) return;

    try {
      // Get current roles
      const currentRoles = selectedUser.roles?.map(r => r.id) || [];

      // Determine roles to add and remove
      const rolesToAdd = assigningRoles.filter(id => !currentRoles.includes(id));
      const rolesToRemove = currentRoles.filter(id => !assigningRoles.includes(id));

      // Remove roles
      for (const roleId of rolesToRemove) {
        await fetch(`/api/user-roles/unassign/${selectedUser.id}/${roleId}`, {
          method: "DELETE",
          headers: {
            Authorization: `Bearer ${localStorage.getItem("ihp_access_token")}`,
          },
        });
      }

      // Add roles
      for (const roleId of rolesToAdd) {
        await fetch("/api/user-roles/assign", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${localStorage.getItem("ihp_access_token")}`,
          },
          body: JSON.stringify({
            user_id: selectedUser.id,
            role_id: roleId,
            is_primary: roleId === primaryRoleId,
          }),
        });
      }

      // Set primary role if changed
      if (primaryRoleId && assigningRoles.includes(primaryRoleId)) {
        await fetch(`/api/user-roles/user/${selectedUser.id}/primary-role/${primaryRoleId}`, {
          method: "POST",
          headers: {
            Authorization: `Bearer ${localStorage.getItem("ihp_access_token")}`,
          },
        });
      }

      setShowRoleAssignModal(false);
      setSelectedUser(null);
      loadData();
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed to assign roles");
    }
  };

  const toggleRoleSelection = (roleId: number) => {
    if (assigningRoles.includes(roleId)) {
      setAssigningRoles(assigningRoles.filter(id => id !== roleId));
      // If removing the primary role, clear primary selection
      if (primaryRoleId === roleId) {
        setPrimaryRoleId(null);
      }
    } else {
      setAssigningRoles([...assigningRoles, roleId]);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto"></div>
          <p className="mt-4 text-gray-600">Loading users...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-8">
        <div className="bg-red-50 border border-red-200 rounded-lg p-4">
          <p className="text-red-800">Error: {error}</p>
          <button
            onClick={loadData}
            className="mt-2 text-red-600 hover:text-red-800 underline"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-7xl mx-auto p-8">
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-gray-900 mb-2">
          User Management
        </h1>
        <p className="text-gray-600">
          Manage user accounts and role assignments
        </p>
      </div>

      {/* Stats Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
        <div className="bg-white paper-surface rounded-lg shadow-sm border border-gray-200 p-4">
          <p className="text-sm text-gray-600 mb-1">Total Users</p>
          <p className="text-2xl font-bold text-gray-900">{users.length}</p>
        </div>
        <div className="bg-white paper-surface rounded-lg shadow-sm border border-gray-200 p-4">
          <p className="text-sm text-gray-600 mb-1">Active Users</p>
          <p className="text-2xl font-bold text-green-600">
            {users.filter((u) => u.is_active).length}
          </p>
        </div>
        <div className="bg-white paper-surface rounded-lg shadow-sm border border-gray-200 p-4">
          <p className="text-sm text-gray-600 mb-1">Total Roles</p>
          <p className="text-2xl font-bold text-blue-600">{roles.length}</p>
        </div>
      </div>

      {/* Users Table */}
      <div className="bg-white paper-surface rounded-lg shadow-sm border border-gray-200 overflow-hidden">
        <table className="min-w-full divide-y divide-gray-200">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                User
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Title
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Email
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Status
              </th>
              <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                Actions
              </th>
            </tr>
          </thead>
          <tbody className="bg-white paper-surface divide-y divide-gray-200">
            {users.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-6 py-12 text-center text-gray-500">
                  No users found.
                </td>
              </tr>
            ) : (
              users.map((user) => (
                <tr key={user.id} className="hover:bg-gray-50">
                  <td className="px-6 py-4">
                    <div>
                      <div className="text-sm font-medium text-gray-900">
                        {user.full_name}
                      </div>
                      <div className="text-xs text-gray-500">@{user.username}</div>
                    </div>
                  </td>
                  <td className="px-6 py-4 text-sm text-gray-900">
                    {user.title || "—"}
                  </td>
                  <td className="px-6 py-4 text-sm text-gray-900">
                    {user.email || "—"}
                  </td>
                  <td className="px-6 py-4">
                    {user.is_active ? (
                      <span className="inline-flex px-2 py-1 text-xs font-medium bg-green-100 text-green-800 rounded">
                        Active
                      </span>
                    ) : (
                      <span className="inline-flex px-2 py-1 text-xs font-medium bg-red-100 text-red-800 rounded">
                        Inactive
                      </span>
                    )}
                  </td>
                  <td className="px-6 py-4 text-right space-x-2">
                    <button
                      onClick={() => loadUserRoles(user.id)}
                      className="text-blue-600 hover:text-blue-900 text-sm font-medium"
                    >
                      Manage Roles
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Role Assignment Modal */}
      {showRoleAssignModal && selectedUser && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white paper-surface rounded-lg shadow-xl max-w-2xl w-full max-h-[90vh] overflow-y-auto m-4">
            <div className="p-6 border-b border-gray-200">
              <h2 className="text-2xl font-bold text-gray-900">
                Assign Roles to {selectedUser.full_name}
              </h2>
              <p className="text-sm text-gray-600 mt-1">
                Select roles and set a primary role for this user
              </p>
            </div>

            <div className="p-6 space-y-4">
              {/* Current Roles Summary */}
              <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
                <p className="text-sm font-medium text-blue-900 mb-2">
                  Current Roles: {assigningRoles.length} selected
                </p>
                {primaryRoleId && (
                  <p className="text-xs text-blue-700">
                    Primary: {roles.find(r => r.id === primaryRoleId)?.display_name}
                  </p>
                )}
              </div>

              {/* Roles List */}
              <div className="space-y-3">
                {roles.map((role) => {
                  const isSelected = assigningRoles.includes(role.id);
                  const isPrimary = primaryRoleId === role.id;

                  return (
                    <div
                      key={role.id}
                      className={`border rounded-lg p-4 transition-all ${
                        isSelected
                          ? "border-blue-500 bg-blue-50"
                          : "border-gray-200 hover:border-gray-300"
                      }`}
                    >
                      <div className="flex items-start gap-3">
                        <input
                          type="checkbox"
                          checked={isSelected}
                          onChange={() => toggleRoleSelection(role.id)}
                          className="mt-1 rounded text-blue-600 focus:ring-blue-500"
                        />
                        <div
                          className="w-4 h-4 rounded mt-1"
                          style={{ backgroundColor: role.color }}
                        ></div>
                        <div className="flex-1">
                          <div className="flex items-center justify-between">
                            <div>
                              <h3 className="text-sm font-medium text-gray-900">
                                {role.display_name}
                              </h3>
                              <p className="text-xs text-gray-500">{role.name}</p>
                            </div>
                            {isSelected && (
                              <button
                                onClick={() => setPrimaryRoleId(role.id)}
                                className={`text-xs px-2 py-1 rounded ${
                                  isPrimary
                                    ? "bg-blue-600 text-white"
                                    : "bg-gray-200 text-gray-700 hover:bg-gray-300"
                                }`}
                              >
                                {isPrimary ? "Primary" : "Set as Primary"}
                              </button>
                            )}
                          </div>
                          {role.discipline && (
                            <span className="inline-flex px-2 py-1 text-xs font-medium bg-gray-100 text-gray-700 rounded mt-1">
                              {role.discipline}
                            </span>
                          )}
                          <p className="text-xs text-gray-600 mt-1">
                            {role.permission_count} permissions
                          </p>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>

              {/* Helper Text */}
              <div className="bg-gray-50 border border-gray-200 rounded-lg p-3">
                <p className="text-xs text-gray-600">
                  💡 <strong>Tip:</strong> Users can have multiple roles. Their
                  effective permissions are the union of all assigned role
                  permissions. The primary role is used for display purposes.
                </p>
              </div>
            </div>

            <div className="p-6 border-t border-gray-200 flex justify-end gap-3">
              <button
                onClick={() => {
                  setShowRoleAssignModal(false);
                  setSelectedUser(null);
                  setAssigningRoles([]);
                  setPrimaryRoleId(null);
                }}
                className="px-4 py-2 bg-gray-200 text-gray-700 rounded-md hover:bg-gray-300"
              >
                Cancel
              </button>
              <button
                onClick={handleAssignRoles}
                className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700"
              >
                Save Role Assignments
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
