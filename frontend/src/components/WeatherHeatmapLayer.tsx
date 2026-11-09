import { useEffect, useRef } from 'react';
import L from 'leaflet';
import { useMap } from 'react-leaflet';
import { heatColor, sampleHourly } from '../lib/heatmap';
import type { HeatmapData } from '../types/routing';

const PANE_NAME = 'weather-heatmap';
const PANE_Z_INDEX = '350';
const METERS_PER_MILE = 1609.344;
const METERS_PER_PIXEL_AT_ZOOM_0 = 156543.03392;
const MIN_RADIUS_PX = 8;
const MAX_RADIUS_PX = 420;

interface WeatherHeatmapLayerProps {
  heatmap: HeatmapData;
  hour: number;
}

function noop(): void {
  return undefined;
}

/**
 * Canvas overlay that paints one radial gradient per corridor sample point.
 *
 * Projection happens only when the map moves. Scrubbing the forecast slider changes `hour`, which
 * is read through a ref and coalesced into a single requestAnimationFrame redraw that does no
 * network work and no React reconciliation of the map tree.
 */
export function WeatherHeatmapLayer({ heatmap, hour }: WeatherHeatmapLayerProps) {
  const map = useMap();
  const hourRef = useRef(hour);
  const requestDrawRef = useRef<() => void>(noop);

  useEffect(() => {
    const pane = map.getPane(PANE_NAME) ?? map.createPane(PANE_NAME);
    pane.style.zIndex = PANE_Z_INDEX;
    pane.style.pointerEvents = 'none';

    const canvas = L.DomUtil.create('canvas', 'leaflet-zoom-hide', pane);
    const context = canvas.getContext('2d');
    if (!context) {
      canvas.remove();
      return undefined;
    }

    const points = heatmap.points;
    const screen = new Float32Array(points.length * 2);
    const values = new Float32Array(points.length);
    const order = points.map((_, index) => index);
    let radiusPx = MIN_RADIUS_PX;
    let ratio = 1;
    let cssWidth = 0;
    let cssHeight = 0;
    let layoutDirty = true;
    let frame = 0;

    const layout = () => {
      const size = map.getSize();
      ratio = window.devicePixelRatio || 1;
      cssWidth = size.x;
      cssHeight = size.y;
      const pixelWidth = Math.round(cssWidth * ratio);
      const pixelHeight = Math.round(cssHeight * ratio);
      if (canvas.width !== pixelWidth || canvas.height !== pixelHeight) {
        canvas.width = pixelWidth;
        canvas.height = pixelHeight;
        canvas.style.width = `${cssWidth}px`;
        canvas.style.height = `${cssHeight}px`;
      }

      const topLeft = map.containerPointToLayerPoint([0, 0]);
      L.DomUtil.setPosition(canvas, topLeft);
      points.forEach((point, index) => {
        const projected = map.latLngToLayerPoint([point.lat, point.lon]);
        screen[index * 2] = projected.x - topLeft.x;
        screen[index * 2 + 1] = projected.y - topLeft.y;
      });

      const latitude = (map.getCenter().lat * Math.PI) / 180;
      const metersPerPixel = (METERS_PER_PIXEL_AT_ZOOM_0 * Math.cos(latitude)) / 2 ** map.getZoom();
      const radius = (heatmap.radius_miles * METERS_PER_MILE) / metersPerPixel;
      radiusPx = Math.min(Math.max(radius, MIN_RADIUS_PX), MAX_RADIUS_PX);
    };

    const draw = () => {
      if (layoutDirty) {
        layout();
        layoutDirty = false;
      }
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
      context.clearRect(0, 0, cssWidth, cssHeight);

      const currentHour = hourRef.current;
      for (let index = 0; index < points.length; index += 1) {
        values[index] = sampleHourly(points[index].risk, currentHour);
      }
      order.sort((a, b) => values[a] - values[b]);

      for (const index of order) {
        const x = screen[index * 2];
        const y = screen[index * 2 + 1];
        if (x < -radiusPx || y < -radiusPx || x > cssWidth + radiusPx || y > cssHeight + radiusPx) continue;

        const [red, green, blue, alpha] = heatColor(values[index]);
        const color = `${Math.round(red)},${Math.round(green)},${Math.round(blue)}`;
        const gradient = context.createRadialGradient(x, y, 0, x, y, radiusPx);
        gradient.addColorStop(0, `rgba(${color},${alpha.toFixed(3)})`);
        gradient.addColorStop(0.55, `rgba(${color},${(alpha * 0.5).toFixed(3)})`);
        gradient.addColorStop(1, `rgba(${color},0)`);
        context.fillStyle = gradient;
        context.fillRect(x - radiusPx, y - radiusPx, radiusPx * 2, radiusPx * 2);
      }
    };

    const requestDraw = () => {
      if (frame !== 0) return;
      frame = requestAnimationFrame(() => {
        frame = 0;
        draw();
      });
    };

    const invalidate = () => {
      layoutDirty = true;
      requestDraw();
    };

    map.on('move zoom moveend zoomend viewreset resize', invalidate);
    requestDrawRef.current = requestDraw;
    invalidate();

    return () => {
      map.off('move zoom moveend zoomend viewreset resize', invalidate);
      if (frame !== 0) cancelAnimationFrame(frame);
      requestDrawRef.current = noop;
      canvas.remove();
    };
  }, [map, heatmap]);

  useEffect(() => {
    hourRef.current = hour;
    requestDrawRef.current();
  }, [hour]);

  return null;
}
