/**
 * Roles & Permissions Management Page
 * Admin interface for managing roles, permissions, and user assignments
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

interface DisciplineInfo {
  code: string;
  display_name: string;
}

interface ResourceTypeInfo {
  code: string;
  display_name: string;
  description: string;
}

interface SystemInfo {
  disciplines: DisciplineInfo[];
  resource_types: ResourceTypeInfo[];
  permission_actions: string[];
}

export default function RolesManagementPage() {
  const router = useRouter();
  const [roles, setRoles] = useState<Role[]>([]);
  const [systemInfo, setSystemInfo] = useState<SystemInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filterDiscipline, setFilterDiscipline] = useState<string>("");
  const [showCreateModal, setShowCreateModal] = useState(false);

  useEffect(() => {
    loadData();
  }, [filterDiscipline]);

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

      // Load roles
      const rolesUrl = filterDiscipline
        ? `/api/roles/?discipline=${filterDiscipline}`
        : "/api/roles/";

      const rolesResponse = await fetch(rolesUrl, {
        headers: {
          Authorization: `Bearer ${localStorage.getItem("ihp_access_token")}`,
        },
      });

      if (!rolesResponse.ok) throw new Error("Failed to load roles");
      const rolesData = await rolesResponse.json();
      setRoles(rolesData);

      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "An error occurred");
    } finally {
      setLoading(false);
    }
  };

  const handleViewRole = (roleId: number) => {
    router.push(`/admin/roles/${roleId}`);
  };

  const handleCreateRole = () => {
    setShowCreateModal(true);
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto"></div>
          <p className="mt-4 text-gray-600">Loading roles...</p>
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
          Roles & Permissions
        </h1>
        <p className="text-gray-600">
          Manage user roles and permissions across the system
        </p>
      </div>

      {/* Actions Bar */}
      <div className="bg-white paper-surface rounded-lg shadow-sm border border-gray-200 p-4 mb-6">
        <div className="flex flex-wrap items-center gap-4">
          {/* Filter by Discipline */}
          <div className="flex-1 min-w-64">
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Filter by Discipline
            </label>
            <select
              value={filterDiscipline}
              onChange={(e) => setFilterDiscipline(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="">All Disciplines</option>
              {systemInfo?.disciplines.map((d) => (
                <option key={d.code} value={d.code}>
                  {d.display_name}
                </option>
              ))}
            </select>
          </div>

          {/* Create Button */}
          <div className="flex items-end">
            <button
              onClick={handleCreateRole}
              className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
            >
              + Create New Role
            </button>
          </div>
        </div>
      </div>

      {/* Stats Cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
        <div className="bg-white paper-surface rounded-lg shadow-sm border border-gray-200 p-4">
          <p className="text-sm text-gray-600 mb-1">Total Roles</p>
          <p className="text-2xl font-bold text-gray-900">{roles.length}</p>
        </div>
        <div className="bg-white paper-surface rounded-lg shadow-sm border border-gray-200 p-4">
          <p className="text-sm text-gray-600 mb-1">System Roles</p>
          <p className="text-2xl font-bold text-blue-600">
            {roles.filter((r) => r.is_system).length}
          </p>
        </div>
        <div className="bg-white paper-surface rounded-lg shadow-sm border border-gray-200 p-4">
          <p className="text-sm text-gray-600 mb-1">Custom Roles</p>
          <p className="text-2xl font-bold text-green-600">
            {roles.filter((r) => !r.is_system).length}
          </p>
        </div>
        <div className="bg-white paper-surface rounded-lg shadow-sm border border-gray-200 p-4">
          <p className="text-sm text-gray-600 mb-1">Active Roles</p>
          <p className="text-2xl font-bold text-gray-900">
            {roles.filter((r) => r.is_active).length}
          </p>
        </div>
      </div>

      {/* Roles Grid */}
      <div className="bg-white paper-surface rounded-lg shadow-sm border border-gray-200 overflow-hidden">
        <table className="min-w-full divide-y divide-gray-200">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Role
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Discipline
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Type
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Permissions
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Users
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
            {roles.length === 0 ? (
              <tr>
                <td colSpan={7} className="px-6 py-12 text-center text-gray-500">
                  No roles found. Create your first role to get started.
                </td>
              </tr>
            ) : (
              roles.map((role) => (
                <tr
                  key={role.id}
                  className="hover:bg-gray-50 cursor-pointer"
                  onClick={() => handleViewRole(role.id)}
                >
                  <td className="px-6 py-4 whitespace-nowrap">
                    <div className="flex items-center">
                      <div
                        className="w-3 h-3 rounded-full mr-3"
                        style={{ backgroundColor: role.color }}
                      ></div>
                      <div>
                        <div className="text-sm font-medium text-gray-900">
                          {role.display_name}
                        </div>
                        <div className="text-xs text-gray-500">{role.name}</div>
                      </div>
                    </div>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    {role.discipline ? (
                      <span className="inline-flex px-2 py-1 text-xs font-medium bg-blue-100 text-blue-800 rounded">
                        {systemInfo?.disciplines.find(
                          (d) => d.code === role.discipline
                        )?.display_name || role.discipline}
                      </span>
                    ) : (
                      <span className="text-sm text-gray-400">—</span>
                    )}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    {role.is_system ? (
                      <span className="inline-flex px-2 py-1 text-xs font-medium bg-purple-100 text-purple-800 rounded">
                        System
                      </span>
                    ) : (
                      <span className="inline-flex px-2 py-1 text-xs font-medium bg-gray-100 text-gray-800 rounded">
                        Custom
                      </span>
                    )}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                    {role.permission_count}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                    {role.user_count}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    {role.is_active ? (
                      <span className="inline-flex px-2 py-1 text-xs font-medium bg-green-100 text-green-800 rounded">
                        Active
                      </span>
                    ) : (
                      <span className="inline-flex px-2 py-1 text-xs font-medium bg-red-100 text-red-800 rounded">
                        Inactive
                      </span>
                    )}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        handleViewRole(role.id);
                      }}
                      className="text-blue-600 hover:text-blue-900"
                    >
                      View →
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Quick Actions */}
      <div className="mt-6 flex gap-4">
        <button
          onClick={() => router.push("/admin/roles/dashboard")}
          className="px-4 py-2 bg-white paper-surface border border-gray-300 text-gray-700 rounded-md hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          View Dashboard
        </button>
        <button
          onClick={() => router.push("/admin/users")}
          className="px-4 py-2 bg-white paper-surface border border-gray-300 text-gray-700 rounded-md hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          Manage Users
        </button>
      </div>
    </div>
  );
}
