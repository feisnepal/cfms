/** Base map tile layer selector with OpenStreetMap/satellite layer toggle. */
import React from 'react';
import { TileLayer, LayersControl } from 'react-leaflet';

const { BaseLayer } = LayersControl;

/**
 * BaseMapSelector provides base layer tiles with a switcher control
 * Usage: Add this component inside MapContainer alongside other map elements
 */
interface BaseMapSelectorProps {
  baseMap?: string;
}

export const BaseMapSelector: React.FC<BaseMapSelectorProps> = () => {
  return (
    <>
      <LayersControl position="topright">
        <BaseLayer name="Satellite Imagery" checked>
          <TileLayer
            attribution='&copy; <a href="https://www.esri.com/">Esri</a>'
            url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
            maxZoom={19}
          />
        </BaseLayer>
        <BaseLayer name="Street Map">
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            maxZoom={19}
          />
        </BaseLayer>
        <BaseLayer name="Topographic Map">
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
            url="https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png"
            maxZoom={17}
          />
        </BaseLayer>
      </LayersControl>
    </>
  );
};

export default BaseMapSelector;
