import React, { useEffect, useState } from "react";
import { SecureAPI } from "../lib/secureApi";
import { useAuth } from "../contexts/AuthContext.new";

interface RevenueData {
  property_id: string;
  total_revenue: string;
  currency: string;
  reservations_count: number;
}

interface RevenueSummaryProps {
  propertyId?: string;
  month?: number;
  year?: number;
  showRaw?: boolean;
}

export const RevenueSummary: React.FC<RevenueSummaryProps> = ({
  propertyId = "prop-001", month, year, showRaw
}) => {
  const { user } = useAuth();
  const [data, setData] = useState<RevenueData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    setLoading(true);
    setData(null);
    setError("");
    SecureAPI.getDashboardSummary(propertyId, { month, year }).then(response => {
      if (active) setData(response);
    }).catch(() => {
      if (active) setError("Failed to load revenue data");
    }).finally(() => {
      if (active) setLoading(false);
    });
    // Ignore responses belonging to a previous property, period, or account.
    return () => { active = false; };
  }, [propertyId, month, year, user?.id, user?.tenant_id]);

  if (loading) return <div className="p-6 animate-pulse">Loading revenue...</div>;
  if (error) return <div role="alert" className="p-4 text-red-500 bg-red-50 rounded-lg">{error}</div>;
  if (!data) return null;

  // Backend sends an already rounded decimal string. Do not re-round using JS floats.
  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
      {showRaw && <pre className="text-xs overflow-auto">{JSON.stringify(data, null, 2)}</pre>}
      <h2 className="text-sm font-medium text-gray-500 uppercase">Total Revenue</h2>
      <p className="text-3xl font-bold text-gray-900 mt-2 mb-6">{data.currency} {data.total_revenue}</p>
      <div className="grid grid-cols-2 gap-4 pt-4 border-t border-gray-100">
        <div><p className="text-xs text-gray-500">Property ID</p><p className="font-mono">{data.property_id}</p></div>
        <div><p className="text-xs text-gray-500">Reservations</p><p>{data.reservations_count} bookings</p></div>
      </div>
    </div>
  );
};

