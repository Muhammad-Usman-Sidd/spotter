import { memo, useEffect, useRef, useState } from 'react';
import L from 'leaflet';
import {
  Circle,
  CircleMarker,
  MapContainer,
  Polyline,
  Popup,
  TileLayer,
  Tooltip,
  ZoomControl,
  useMap,
} from 'react-leaflet';
import { formatClock, formatDuration, formatMiles } from '../lib/format';
import { RISK_COLORS, RISK_LABELS } from '../lib/risk';
import type { Checkpoint, CheckpointFocus, DemoStormInfo, RouteOption, TripPlan } from '../types/routing';
import { ForecastSlider } from './ForecastSlider';
import { WeatherHeatmapLayer } from './WeatherHeatmapLayer';

const INITIAL_CENTER: [number, number] = [39.5, -98.35];
const INITIAL_ZOOM = 4;
const TILE_URL = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';
const TILE_ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';
const METERS_PER_MILE = 1609.344;
const SELECTED_ROUTE_COLOR = '#38bdf8';
const OTHER_ROUTE_COLOR = '#64748b';

interface RouteMapProps {
  plan: TripPlan;
  selectedRoute: RouteOption;
  focus: CheckpointFocus | null;
  onSelectRoute: (id: string) => void;
}

function arrivalTime(route: RouteOption): string {
  const last = route.checkpoints[route.checkpoints.length - 1];
  return last ? formatClock(last.eta) : '';
}

/** Fits the selected route, or zooms to the focused checkpoint when one is picked from the table. */
function MapViewport({ route, focus }: { route: RouteOption; focus: CheckpointFocus | null }) {
  const map = useMap();

  useEffect(() => {
    const checkpoint = focus ? route.checkpoints[focus.index] : undefined;
    if (checkpoint) {
      map.setView([checkpoint.lat, checkpoint.lon], Math.max(map.getZoom(), 9), { animate: false });
      return;
    }
    // Top padding leaves room for the route summary table, bottom padding for the forecast slider.
    map.fitBounds(L.latLngBounds(route.geometry), {
      paddingTopLeft: [48, 130],
      paddingBottomRight: [48, 150],
    });
  }, [map, route, focus]);

  return null;
}

function RouteSummaryText({ route }: { route: RouteOption }) {
  const { summary } = route;
  return (
    <div className="text-xs tabular-nums">
      <div className="font-semibold text-slate-100">
        #{route.rank} {route.name}
        {route.recommended && <span className="ml-1.5 text-emerald-400">Recommended</span>}
      </div>
      <div className="text-slate-300">
        {formatMiles(route.distance_miles)} mi, {formatDuration(route.duration_minutes)}, arrives {arrivalTime(route)}
      </div>
      <div className="text-slate-400">
        No Travel {formatMiles(summary.no_travel_miles)} mi, Severe {formatMiles(summary.severe_miles)} mi, High{' '}
        {formatMiles(summary.high_miles)} mi, avg risk {summary.average_risk_score.toFixed(2)}
      </div>
    </div>
  );
}

interface RouteLinesProps {
  routes: RouteOption[];
  selectedId: string;
  onSelectRoute: (id: string) => void;
}

const RouteLines = memo(function RouteLines({ routes, selectedId, onSelectRoute }: RouteLinesProps) {
  const otherRoutes = routes.filter((route) => route.id !== selectedId);
  const selectedRoutes = routes.filter((route) => route.id === selectedId);
  const drawOrder = [...otherRoutes, ...selectedRoutes];

  return (
    <>
      {drawOrder.map((route) => {
        const selected = route.id === selectedId;
        return (
          <Polyline
            key={route.id}
            positions={route.geometry}
            pathOptions={{
              color: selected ? SELECTED_ROUTE_COLOR : OTHER_ROUTE_COLOR,
              weight: selected ? 5 : 3,
              opacity: selected ? 0.95 : 0.7,
              dashArray: selected ? undefined : '6 6',
            }}
            eventHandlers={{ click: () => onSelectRoute(route.id) }}
          >
            <Tooltip sticky className="map-tooltip">
              <RouteSummaryText route={route} />
            </Tooltip>
          </Polyline>
        );
      })}
    </>
  );
});

function CheckpointPopup({ route, checkpoint }: { route: RouteOption; checkpoint: Checkpoint }) {
  return (
    <div className="text-xs tabular-nums">
      <div className="mb-1 font-semibold text-slate-100">{route.name}</div>
      <dl className="grid grid-cols-[auto_auto] gap-x-4 gap-y-0.5">
        <dt className="text-slate-400">Mile marker</dt>
        <dd className="text-right text-slate-100">{checkpoint.mile.toFixed(1)}</dd>
        <dt className="text-slate-400">ETA</dt>
        <dd className="text-right text-slate-100">{formatClock(checkpoint.eta)}</dd>
        <dt className="text-slate-400">Wind</dt>
        <dd className="text-right text-slate-100">{checkpoint.wind_mph.toFixed(1)} mph</dd>
        <dt className="text-slate-400">Rain</dt>
        <dd className="text-right text-slate-100">{checkpoint.rain_in_hr.toFixed(2)} in/hr</dd>
        <dt className="text-slate-400">Snow</dt>
        <dd className="text-right text-slate-100">{checkpoint.snow_in_hr.toFixed(2)} in/hr</dd>
        <dt className="text-slate-400">Risk level</dt>
        <dd className="text-right font-semibold" style={{ color: RISK_COLORS[checkpoint.risk_level] }}>
          {RISK_LABELS[checkpoint.risk_level]}
        </dd>
        <dt className="text-slate-400">Load escalation</dt>
        <dd className="text-right text-slate-100">{checkpoint.load_escalated ? 'Triggered' : 'No'}</dd>
      </dl>
      {checkpoint.load_rule && <p className="mt-1 max-w-[16rem] text-amber-300">{checkpoint.load_rule}</p>}
    </div>
  );
}

function SelectedRouteCheckpoints({ route, focus }: { route: RouteOption; focus: CheckpointFocus | null }) {
  const markers = useRef<Array<L.CircleMarker | null>>([]);

  useEffect(() => {
    if (!focus) return undefined;
    const timer = window.setTimeout(() => markers.current[focus.index]?.openPopup(), 0);
    return () => window.clearTimeout(timer);
  }, [route, focus]);

  return (
    <>
      {route.checkpoints.map((checkpoint, index) => (
        <CircleMarker
          key={`${route.id}-${checkpoint.mile}`}
          ref={(marker) => {
            markers.current[index] = marker;
          }}
          center={[checkpoint.lat, checkpoint.lon]}
          radius={focus?.index === index ? 8 : 5}
          pathOptions={{
            color: '#020617',
            weight: 1.5,
            fillColor: RISK_COLORS[checkpoint.risk_level],
            fillOpacity: 1,
          }}
        >
          <Popup>
            <CheckpointPopup route={route} checkpoint={checkpoint} />
          </Popup>
        </CircleMarker>
      ))}
    </>
  );
}

interface OtherRouteCheckpointsProps {
  routes: RouteOption[];
  selectedId: string;
  onSelectRoute: (id: string) => void;
}

/** Smaller, dimmer markers for the routes that are not selected; clicking one selects its route. */
const OtherRouteCheckpoints = memo(function OtherRouteCheckpoints({
  routes,
  selectedId,
  onSelectRoute,
}: OtherRouteCheckpointsProps) {
  const otherRoutes = routes.filter((route) => route.id !== selectedId);
  return (
    <>
      {otherRoutes.map((route) =>
        route.checkpoints.map((checkpoint) => (
          <CircleMarker
            key={`${route.id}-${checkpoint.mile}`}
            center={[checkpoint.lat, checkpoint.lon]}
            radius={3}
            pathOptions={{
              color: '#020617',
              weight: 1,
              fillColor: RISK_COLORS[checkpoint.risk_level],
              fillOpacity: 0.6,
            }}
            eventHandlers={{ click: () => onSelectRoute(route.id) }}
          >
            <Tooltip className="map-tooltip">
              <span className="text-xs tabular-nums text-slate-200">
                {route.name}, mile {checkpoint.mile.toFixed(1)}, ETA {formatClock(checkpoint.eta)},{' '}
                {RISK_LABELS[checkpoint.risk_level]}
              </span>
            </Tooltip>
          </CircleMarker>
        )),
      )}
    </>
  );
});

function StormMarker({ storm }: { storm: DemoStormInfo }) {
  return (
    <Circle
      center={[storm.center_lat, storm.center_lon]}
      radius={storm.radius_miles * METERS_PER_MILE}
      pathOptions={{ color: '#f59e0b', weight: 1.5, dashArray: '4 6', fill: false, interactive: false }}
    >
      <Tooltip permanent direction="center" className="storm-label">
        Demo storm (synthetic)
      </Tooltip>
    </Circle>
  );
}

interface MapRouteSummaryProps {
  routes: RouteOption[];
  selectedId: string;
  onSelectRoute: (id: string) => void;
}

/** Route summaries pinned on the map, so the comparison is visible without opening the sidebar. */
function MapRouteSummary({ routes, selectedId, onSelectRoute }: MapRouteSummaryProps) {
  return (
    <div className="absolute left-3 top-3 z-[1000] hidden rounded border border-slate-700 bg-slate-900/90 shadow-lg md:block">
      <table className="text-[11px] tabular-nums" aria-label="Route summaries on map">
        <thead className="text-left uppercase tracking-wider text-slate-500">
          <tr>
            <th className="px-2 pb-1 pt-1.5 font-medium">Route</th>
            <th className="px-2 pb-1 pt-1.5 text-right font-medium">Miles</th>
            <th className="px-2 pb-1 pt-1.5 text-right font-medium">Transit</th>
            <th className="px-2 pb-1 pt-1.5 text-right font-medium">Arrive</th>
            <th className="px-2 pb-1 pt-1.5 text-right font-medium">No Travel</th>
            <th className="px-2 pb-1 pt-1.5 text-right font-medium">Severe</th>
            <th className="px-2 pb-1 pt-1.5 text-right font-medium">Avg</th>
          </tr>
        </thead>
        <tbody>
          {routes.map((route) => {
            const selected = route.id === selectedId;
            return (
              <tr key={route.id} className={selected ? 'bg-slate-800 text-slate-100' : 'text-slate-300'}>
                <td className="px-2 py-1">
                  <button
                    type="button"
                    onClick={() => onSelectRoute(route.id)}
                    aria-pressed={selected}
                    className="max-w-[9rem] truncate text-left font-medium hover:text-sky-300"
                    title={route.name}
                  >
                    #{route.rank} {route.name}
                  </button>
                </td>
                <td className="px-2 py-1 text-right">{formatMiles(route.distance_miles)}</td>
                <td className="px-2 py-1 text-right">{formatDuration(route.duration_minutes)}</td>
                <td className="whitespace-nowrap px-2 py-1 text-right">{arrivalTime(route)}</td>
                <td className="px-2 py-1 text-right">{formatMiles(route.summary.no_travel_miles)}</td>
                <td className="px-2 py-1 text-right">{formatMiles(route.summary.severe_miles)}</td>
                <td className="px-2 py-1 text-right">{route.summary.average_risk_score.toFixed(2)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function RouteMap({ plan, selectedRoute, focus, onSelectRoute }: RouteMapProps) {
  const storm = plan.meta.demo_storm;
  const initialHour = storm ? Math.min(storm.peak_offset_hours, plan.heatmap.max_offset_hours) : 0;
  const [hour, setHour] = useState(initialHour);

  useEffect(() => {
    setHour(initialHour);
  }, [plan, initialHour]);

  return (
    <div className="relative h-full w-full">
      <MapContainer center={INITIAL_CENTER} zoom={INITIAL_ZOOM} preferCanvas zoomControl={false} className="h-full w-full">
        <TileLayer url={TILE_URL} attribution={TILE_ATTRIBUTION} maxZoom={19} className="dark-basemap" />
        <ZoomControl position="topright" />
        <WeatherHeatmapLayer heatmap={plan.heatmap} hour={hour} />
        {storm && <StormMarker storm={storm} />}
        <RouteLines routes={plan.routes} selectedId={selectedRoute.id} onSelectRoute={onSelectRoute} />
        <OtherRouteCheckpoints routes={plan.routes} selectedId={selectedRoute.id} onSelectRoute={onSelectRoute} />
        <SelectedRouteCheckpoints route={selectedRoute} focus={focus} />
        <MapViewport route={selectedRoute} focus={focus} />
      </MapContainer>
      <MapRouteSummary routes={plan.routes} selectedId={selectedRoute.id} onSelectRoute={onSelectRoute} />
      <ForecastSlider heatmap={plan.heatmap} hour={hour} onHourChange={setHour} />
    </div>
  );
}
