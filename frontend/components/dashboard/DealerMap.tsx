"use client";

import React, { useState, useEffect, memo, useRef } from "react";
import {
  ComposableMap,
  Geographies,
  Geography,
  Marker,
  ZoomableGroup,
} from "react-simple-maps";
import { MapPin } from "lucide-react";

// US Atlas TopoJSON - free and reliable source
const geoUrl = "https://cdn.jsdelivr.net/npm/us-atlas@3/states-10m.json";

interface Distributor {
  id: string;
  name: string;
  region?: string;
  status: string;
  match_count?: number;
  has_violation?: boolean;
  violation_count?: number;
  metadata?: {
    latitude?: number;
    longitude?: number;
    lat?: number;
    lng?: number;
  };
}

interface DealerMapProps {
  distributors: Distributor[];
}

// US state coordinates for fallback positioning based on region
const stateCoordinates: Record<string, [number, number]> = {
  "Alabama": [-86.9023, 32.3182],
  "Alaska": [-153.4937, 64.2008],
  "Arizona": [-111.0937, 34.0489],
  "Arkansas": [-92.3731, 34.7465],
  "California": [-119.4179, 36.7783],
  "Colorado": [-105.3111, 39.0598],
  "Connecticut": [-72.7554, 41.5978],
  "Delaware": [-75.5277, 38.9108],
  "Florida": [-81.5158, 27.6648],
  "Georgia": [-83.6431, 32.1574],
  "Hawaii": [-155.5828, 19.8968],
  "Idaho": [-114.7420, 44.0682],
  "Illinois": [-89.3985, 40.6331],
  "Indiana": [-86.1349, 40.2672],
  "Iowa": [-93.0977, 41.8780],
  "Kansas": [-98.4842, 39.0119],
  "Kentucky": [-84.2700, 37.8393],
  "Louisiana": [-91.9623, 30.9843],
  "Maine": [-69.4455, 45.2538],
  "Maryland": [-76.6413, 39.0458],
  "Massachusetts": [-71.3824, 42.4072],
  "Michigan": [-85.6024, 44.3148],
  "Minnesota": [-94.6859, 46.7296],
  "Mississippi": [-89.3985, 32.3547],
  "Missouri": [-91.8318, 37.9643],
  "Montana": [-110.3626, 46.8797],
  "Nebraska": [-99.9018, 41.4925],
  "Nevada": [-116.4194, 38.8026],
  "New Hampshire": [-71.5724, 43.1939],
  "New Jersey": [-74.4057, 40.0583],
  "New Mexico": [-105.8701, 34.5199],
  "New York": [-75.4999, 43.2994],
  "North Carolina": [-79.0193, 35.7596],
  "North Dakota": [-101.0020, 47.5515],
  "Ohio": [-82.9071, 40.4173],
  "Oklahoma": [-97.5164, 35.0078],
  "Oregon": [-120.5542, 43.8041],
  "Pennsylvania": [-77.1945, 41.2033],
  "Rhode Island": [-71.4774, 41.5801],
  "South Carolina": [-81.1637, 33.8361],
  "South Dakota": [-99.9018, 43.9695],
  "Tennessee": [-86.5804, 35.5175],
  "Texas": [-99.9018, 31.9686],
  "Utah": [-111.0937, 39.3210],
  "Vermont": [-72.5778, 44.5588],
  "Virginia": [-78.6569, 37.4316],
  "Washington": [-120.7401, 47.7511],
  "West Virginia": [-80.4549, 38.5976],
  "Wisconsin": [-89.6165, 43.7844],
  "Wyoming": [-107.2903, 43.0760],
  // Region shortcuts
  "Northeast": [-73.9857, 40.7484],
  "Southeast": [-84.3880, 33.7490],
  "Midwest": [-87.6298, 41.8781],
  "Southwest": [-112.0740, 33.4484],
  "West": [-118.2437, 34.0522],
  "Northwest": [-122.3321, 47.6062],
  "Central": [-97.7431, 30.2672],
};

// State abbreviation to full name mapping
const stateAbbreviations: Record<string, string> = {
  "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
  "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
  "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
  "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
  "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
  "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
  "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
  "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
  "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
  "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
  "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
  "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
  "WI": "Wisconsin", "WY": "Wyoming",
};

// Major US cities with coordinates [longitude, latitude]
const cityCoordinates: Record<string, [number, number]> = {
  // Texas
  "Houston": [-95.3698, 29.7604],
  "Dallas": [-96.7970, 32.7767],
  "Austin": [-97.7431, 30.2672],
  "San Antonio": [-98.4936, 29.4241],
  "Fort Worth": [-97.3308, 32.7555],
  "El Paso": [-106.4850, 31.7619],
  // California
  "Los Angeles": [-118.2437, 34.0522],
  "San Francisco": [-122.4194, 37.7749],
  "San Diego": [-117.1611, 32.7157],
  "San Jose": [-121.8863, 37.3382],
  "Sacramento": [-121.4944, 38.5816],
  // Florida
  "Miami": [-80.1918, 25.7617],
  "Orlando": [-81.3792, 28.5383],
  "Tampa": [-82.4572, 27.9506],
  "Jacksonville": [-81.6557, 30.3322],
  // New York
  "New York City": [-74.0060, 40.7128],
  "NYC": [-74.0060, 40.7128],
  "Buffalo": [-78.8784, 42.8864],
  // Illinois
  "Chicago": [-87.6298, 41.8781],
  // Pennsylvania
  "Philadelphia": [-75.1652, 39.9526],
  "Pittsburgh": [-79.9959, 40.4406],
  // Arizona
  "Phoenix": [-112.0740, 33.4484],
  "Tucson": [-110.9747, 32.2226],
  // Georgia
  "Atlanta": [-84.3880, 33.7490],
  // Washington
  "Seattle": [-122.3321, 47.6062],
  // Massachusetts
  "Boston": [-71.0589, 42.3601],
  // Colorado
  "Denver": [-104.9903, 39.7392],
  // Tennessee
  "Nashville": [-86.7816, 36.1627],
  "Memphis": [-90.0490, 35.1495],
  "Knoxville": [-83.9207, 35.9606],
  // Michigan
  "Detroit": [-83.0458, 42.3314],
  // Minnesota
  "Minneapolis": [-93.2650, 44.9778],
  // Ohio
  "Columbus": [-82.9988, 39.9612],
  "Cleveland": [-81.6944, 41.4993],
  "Cincinnati": [-84.5120, 39.1031],
  // Oregon
  "Portland": [-122.6750, 45.5051],
  // Nevada
  "Las Vegas": [-115.1398, 36.1699],
  // Missouri
  "Kansas City": [-94.5786, 39.0997],
  "St. Louis": [-90.1994, 38.6270],
  // North Carolina
  "Charlotte": [-80.8431, 35.2271],
  "Raleigh": [-78.6382, 35.7796],
  // Louisiana
  "New Orleans": [-90.0715, 29.9511],
  // Indiana
  "Indianapolis": [-86.1581, 39.7684],
  // Wisconsin
  "Milwaukee": [-87.9065, 43.0389],
  // Maryland
  "Baltimore": [-76.6122, 39.2904],
  // Oklahoma
  "Oklahoma City": [-97.5164, 35.4676],
  "Tulsa": [-95.9928, 36.1540],
  // Utah
  "Salt Lake City": [-111.8910, 40.7608],
  // Kentucky
  "Louisville": [-85.7585, 38.2527],
  // Alabama
  "Birmingham": [-86.8025, 33.5207],
  // South Carolina
  "Charleston": [-79.9311, 32.7765],
};

type FilterType = 'all' | 'compliant' | 'violations';

function DealerMap({ distributors }: DealerMapProps) {
  const [mounted, setMounted] = useState(false);
  const [filter, setFilter] = useState<FilterType>('all');
  const [tooltipContent, setTooltipContent] = useState<{
    name: string;
    region: string;
    isViolator: boolean;
    x: number;
    y: number;
  } | null>(null);
  const mapContainerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setMounted(true);
  }, []);

  // Debug: Log distributor violation data
  useEffect(() => {
    if (distributors.length > 0) {
      console.log('[DealerMap] Distributors with violation data:', 
        distributors.map(d => ({
          name: d.name,
          has_violation: d.has_violation,
          violation_count: d.violation_count,
          match_count: d.match_count
        }))
      );
    }
  }, [distributors]);


  if (!mounted) {
    return (
      <div className="h-[400px] w-full bg-secondary/20 animate-pulse flex items-center justify-center text-muted-foreground">
        Loading Map...
      </div>
    );
  }

  // Get coordinates for a distributor
  const getCoordinates = (dist: Distributor, index: number): [number, number] => {
    // Try metadata first
    if (dist.metadata?.longitude && dist.metadata?.latitude) {
      return [dist.metadata.longitude, dist.metadata.latitude];
    }
    if (dist.metadata?.lng && dist.metadata?.lat) {
      return [dist.metadata.lng, dist.metadata.lat];
    }
    
    // Try region matching (case-insensitive, with abbreviation and city support)
    if (dist.region) {
      const regionTrimmed = dist.region.trim();
      const regionUpper = regionTrimmed.toUpperCase();
      const regionLower = regionTrimmed.toLowerCase();
      
      // First check if it's a state abbreviation (e.g., "TX", "FL")
      const fullStateName = stateAbbreviations[regionUpper];
      if (fullStateName && stateCoordinates[fullStateName]) {
        const regionCoord = stateCoordinates[fullStateName];
        const offset = (index % 5) * 0.5;
        return [regionCoord[0] + offset, regionCoord[1] + offset];
      }
      
      // Check if it's a city name (case-insensitive)
      const matchingCity = Object.keys(cityCoordinates).find(
        city => city.toLowerCase() === regionLower
      );
      if (matchingCity) {
        const cityCoord = cityCoordinates[matchingCity];
        const offset = (index % 5) * 0.3; // Smaller offset for cities
        return [cityCoord[0] + offset, cityCoord[1] + offset];
      }
      
      // Find the matching state coordinate key (case-insensitive)
      const matchingKey = Object.keys(stateCoordinates).find(
        key => key.toLowerCase() === regionLower
      );
      if (matchingKey) {
        const regionCoord = stateCoordinates[matchingKey];
        // Add small offset based on index to prevent overlap
        const offset = (index % 5) * 0.5;
        return [regionCoord[0] + offset, regionCoord[1] + offset];
      }
    }
    
    // Generate pseudo-random but consistent US coordinates as fallback
    const seed = dist.id.split('').reduce((acc, char) => acc + char.charCodeAt(0), 0);
    const lng = -120 + ((seed * 7 + index * 13) % 50); // -120 to -70 (US longitude range)
    const lat = 30 + ((seed * 11 + index * 17) % 18);  // 30 to 48 (US latitude range)
    return [lng, lat];
  };

  const compliantCount = distributors.filter(d => !d.has_violation).length;
  const violationCount = distributors.filter(d => d.has_violation).length;
  
  // Filter distributors based on selected filter
  const filteredDistributors = distributors.filter(d => {
    if (filter === 'all') return true;
    if (filter === 'compliant') return !d.has_violation;
    if (filter === 'violations') return d.has_violation;
    return true;
  });

  return (
    <div ref={mapContainerRef} className="h-[400px] w-full bg-[#0d1117] relative overflow-visible">
      {/* Subtle grid overlay */}
      <div 
        className="absolute inset-0 opacity-10 pointer-events-none z-10"
        style={{
          backgroundImage: `
            linear-gradient(rgba(255,255,255,0.03) 1px, transparent 1px),
            linear-gradient(90deg, rgba(255,255,255,0.03) 1px, transparent 1px)
          `,
          backgroundSize: '40px 40px'
        }}
      />

      <ComposableMap
        projection="geoAlbersUsa"
        projectionConfig={{
          scale: 1000,
        }}
        className="w-full h-full"
        style={{ width: "100%", height: "100%" }}
      >
        <ZoomableGroup center={[-96, 38]} zoom={0.85}>
          <Geographies geography={geoUrl}>
            {({ geographies }) =>
              geographies.map((geo) => (
                <Geography
                  key={geo.rsmKey}
                  geography={geo}
                  fill="#1e293b"
                  stroke="#334155"
                  strokeWidth={0.5}
                  style={{
                    default: { outline: "none" },
                    hover: { fill: "#334155", outline: "none" },
                    pressed: { outline: "none" },
                  }}
                />
              ))
            }
          </Geographies>

          {/* Dealer markers */}
          {filteredDistributors.map((dist, idx) => {
            const coords = getCoordinates(dist, idx);
            const isViolator = dist.has_violation === true;

            return (
              <Marker
                key={dist.id}
                coordinates={coords}
                onMouseEnter={(e) => {
                  const containerRect = mapContainerRef.current?.getBoundingClientRect();
                  const markerRect = (e.target as SVGElement).getBoundingClientRect();
                  if (containerRect) {
                    setTooltipContent({
                      name: dist.name,
                      region: dist.region || "Unknown",
                      isViolator,
                      x: markerRect.left - containerRect.left + markerRect.width / 2,
                      y: markerRect.top - containerRect.top,
                    });
                  }
                }}
                onMouseLeave={() => setTooltipContent(null)}
              >
                {/* Glow effect for violations */}
                {isViolator && (
                  <circle
                    r={12}
                    fill="rgba(239, 68, 68, 0.2)"
                    className="animate-pulse"
                  />
                )}
                {/* Main pin */}
                <circle
                  r={6}
                  fill={isViolator ? "#ef4444" : "#22c55e"}
                  stroke={isViolator ? "#fca5a5" : "#86efac"}
                  strokeWidth={2}
                  className="cursor-pointer transition-transform hover:scale-125"
                />
                {/* Center dot */}
                <circle
                  r={2}
                  fill={isViolator ? "#fecaca" : "#bbf7d0"}
                />
              </Marker>
            );
          })}
        </ZoomableGroup>
      </ComposableMap>

      {/* Tooltip */}
      {tooltipContent && (
        <div
          className="absolute z-50 px-3 py-2 bg-popover border border-border rounded-md shadow-lg text-xs pointer-events-none whitespace-nowrap"
          style={{
            left: tooltipContent.x,
            top: tooltipContent.y - 10,
            transform: "translate(-50%, -100%)",
          }}
        >
          <p className="font-medium text-foreground">{tooltipContent.name}</p>
          <p className="text-muted-foreground">{tooltipContent.region}</p>
          <p className={tooltipContent.isViolator ? "text-red-400" : "text-green-400"}>
            {tooltipContent.isViolator ? "⚠ Issues Detected" : "✓ Compliant"}
          </p>
        </div>
      )}

      {/* Legend - clickable for filtering */}
      <div 
        className="absolute bottom-4 left-4 flex items-center gap-2 text-xs bg-background/90 backdrop-blur-sm px-3 py-2 rounded border border-border z-20"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            setFilter(filter === 'compliant' ? 'all' : 'compliant');
          }}
          className={`flex items-center gap-1.5 px-2 py-1 rounded transition-all cursor-pointer ${
            filter === 'compliant' 
              ? 'bg-green-500/20 ring-1 ring-green-500' 
              : 'hover:bg-secondary/50'
          }`}
        >
          <div className="w-3 h-3 rounded-full bg-green-500 border border-green-300" />
          <span className={filter === 'compliant' ? 'text-green-400' : 'text-muted-foreground'}>
            Compliant ({compliantCount})
          </span>
        </button>
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            setFilter(filter === 'violations' ? 'all' : 'violations');
          }}
          className={`flex items-center gap-1.5 px-2 py-1 rounded transition-all cursor-pointer ${
            filter === 'violations' 
              ? 'bg-red-500/20 ring-1 ring-red-500' 
              : 'hover:bg-secondary/50'
          }`}
        >
          <div className="w-3 h-3 rounded-full bg-red-500 border border-red-300" />
          <span className={filter === 'violations' ? 'text-red-400' : 'text-muted-foreground'}>
            Violations ({violationCount})
          </span>
        </button>
        {filter !== 'all' && (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              setFilter('all');
            }}
            className="ml-1 px-2 py-1 text-muted-foreground hover:text-foreground hover:bg-secondary/50 rounded transition-all cursor-pointer"
          >
            Show All
          </button>
        )}
      </div>

      {/* Empty state */}
      {filteredDistributors.length === 0 && (
        <div className="absolute inset-0 flex items-center justify-center text-muted-foreground text-sm z-20">
          {distributors.length === 0 
            ? "No distributors to display" 
            : `No ${filter === 'compliant' ? 'compliant' : 'violating'} distributors`}
        </div>
      )}
    </div>
  );
}

export default memo(DealerMap);
