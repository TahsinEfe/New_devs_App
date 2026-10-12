import React, { useEffect, useState } from "react";
import { RevenueSummary } from "./RevenueSummary";
import { SecureAPI } from "../lib/secureApi";
import { useAuth } from "../contexts/AuthContext.new";

interface Property { id: string; name: string; timezone: string; }

const Dashboard: React.FC = () => {
  const { user } = useAuth();
  const [properties, setProperties] = useState<Property[]>([]);
  const [selectedProperty, setSelectedProperty] = useState("");
  const [period, setPeriod] = useState("monthly");
  const [month, setMonth] = useState(3);
  const [year, setYear] = useState(2024);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    setProperties([]);
    setSelectedProperty("");
    setError("");
    setLoading(true);
    SecureAPI.getDashboardProperties().then((result: Property[]) => {
      if (!active) return;
      setProperties(result);
      setSelectedProperty(result[0]?.id || "");
    }).catch(() => {
      if (active) setError("Failed to load your properties");
    }).finally(() => {
      if (active) setLoading(false);
    });
    return () => { active = false; };
  }, [user?.id, user?.tenant_id]);

  const property = properties.find(item => item.id === selectedProperty);
  return (
    <div className="p-4 lg:p-6 min-h-full">
      <div className="max-w-7xl mx-auto">
        <h1 className="text-2xl font-bold mb-6 text-gray-900">Property Management Dashboard</h1>
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4 lg:p-6">
          <h2 className="text-lg font-medium text-gray-900 mb-2">Revenue Overview</h2>
          <p className="text-sm text-gray-600 mb-4">Revenue by property-local check-in date.</p>
          {loading && <p>Loading properties...</p>}
          {error && <p role="alert" className="text-red-600">{error}</p>}
          {!loading && !error && properties.length === 0 && <p>No properties available.</p>}
          {properties.length > 0 && (
            <>
              <div className="flex flex-wrap gap-4 mb-6">
                <label className="text-sm">Property
                  <select value={selectedProperty} onChange={e => setSelectedProperty(e.target.value)} className="block border rounded p-2">
                    {properties.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
                  </select>
                </label>
                <label className="text-sm">Period
                  <select value={period} onChange={e => setPeriod(e.target.value)} className="block border rounded p-2">
                    <option value="monthly">Monthly</option>
                    <option value="annual">Annual</option>
                    <option value="all">All time</option>
                  </select>
                </label>
                {period === "monthly" && (
                  <label className="text-sm">Month
                    <select value={month} onChange={e => setMonth(Number(e.target.value))} className="block border rounded p-2">
                      {Array.from({ length: 12 }, (_, i) => <option key={i + 1} value={i + 1}>{i + 1}</option>)}
                    </select>
                  </label>
                )}
                {period !== "all" && (
                  <label className="text-sm">Year
                    <input type="number" min={1} max={9998} value={year} onChange={e => setYear(Number(e.target.value))} className="block border rounded p-2 w-24" />
                  </label>
                )}
              </div>
              <p className="text-xs text-gray-500 mb-4">Reporting timezone: {property?.timezone}</p>
              <RevenueSummary key={user?.id} propertyId={selectedProperty}
                month={period === "monthly" ? month : undefined}
                year={period === "all" ? undefined : year} />
            </>
          )}
        </div>
      </div>
    </div>
  );
};

export default Dashboard;
