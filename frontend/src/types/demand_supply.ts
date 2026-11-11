/** Demand-supply analysis TypeScript type definitions. */
export interface DemandSupplyResponse {
  demand: ProductQuantities;
  supply_cf_regular: ProductQuantities;
  supply_cf_aah: ProductQuantities;
  supply_private: ProductQuantities;
  total_supply: ProductQuantities;
  deficit: ProductQuantities;
  nepali_description: string;
}

export interface ProductQuantities {
  firewood_bhari: number | null;
  grass_bhari: number | null;
  bedding_bhari: number | null;
  timber_cft: number | null;
  poles_count: number | null;
}
