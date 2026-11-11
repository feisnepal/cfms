import type L from 'leaflet';

let mapRef: L.Map | null = null;

export function setMapRef(map: L.Map | null): void {
  mapRef = map;
}

export function getMapRef(): L.Map | null {
  return mapRef;
}
