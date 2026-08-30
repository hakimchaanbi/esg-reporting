<!-- cache-meta
model: gemini-3.5-flash
prompt_sha256: f0a6f0ab104acdf3a13b36e83bda13c0164f7a7b882f562a787dd087659f5650
generated: 2026-08-30
-->
### Energy Performance

The total annual energy consumption within the organisation is `{{ op_5_total_annual_energy_consumption }}`. This total comprises electricity consumption of `{{ op_5_total_electricity_consumption }}` and stationary fuel consumption of `{{ op_5_total_stationary_fuel_consumption }}`. The university consumes `{{ op_5_total_heating_and_cooling_from_off_site_sources }}` of heating and cooling from off-site sources, and exports `{{ op_5_on_site_renewable_electricity_exported }}` of on-site renewable electricity.

In terms of fuel composition, natural gas consumption is `{{ op_5_natural_gas }}`. Heating oil consumption is `{{ op_5_heating_oil }}` and coal or coke consumption is `{{ op_5_coal_coke }}`. Propane and liquefied petroleum gas consumption is `{{ op_5_propane_lpg }}`. Annual renewable energy consumption stands at `{{ op_5_annual_renewable_energy_consumption }}`. Renewable stationary fuels account for `{{ op_5_renewable_stationary_fuels }}`.

Energy intensity metrics show an annual energy consumption per person of `{{ op_5_annual_energy_consumption_per_person }}` and an annual energy consumption per unit of floor area of `{{ op_5_annual_energy_consumption_per_unit_of_floor_area }}`.

### Water Performance

The total water withdrawal is `{{ op_3_total_water_withdrawal }}`. This is entirely drawn as potable water from off-site sources, which is `{{ op_3_potable_water_from_off_site_sources }}`. Potable water from on-site sources is `{{ op_3_potable_water_from_on_site_sources }}`.

The physical water quantity risk for the main campus is classified as high. To mitigate water impacts, the university harvests rainwater on-site for storage and use.

### Emissions Performance

Direct Scope 1 greenhouse gas emissions from stationary combustion are `{{ op_6_scope_1_ghg_emissions_from_stationary_combustion }}`. Scope 1 emissions from mobile combustion are `{{ op_6_scope_1_ghg_emissions_from_mobile_combustion }}`. Scope 1 fugitive emissions are `{{ op_6_scope_1_ghg_fugitive_emissions }}`. Greenhouse gas emissions from biogenic sources are `{{ op_6_ghg_emissions_from_biogenic_sources }}`.

Indirect Scope 2 greenhouse gas emissions from off-site sources of electricity, calculated using a market-based method, are `{{ op_6_scope_2_ghg_emissions_from_off_site_sources_of_electric }}`. Scope 2 emissions from off-site sources of heating and cooling are `{{ op_6_scope_2_ghg_emissions_from_off_site_sources_of_heating }}`.

Other indirect Scope 3 emissions include `{{ op_6_scope_3_ghg_emissions_from_business_travel }}` from business travel, `{{ op_6_scope_3_ghg_emissions_from_commuting }}` from commuting, `{{ op_6_scope_3_ghg_emissions_from_waste_generated_in_operation }}` from waste generated in operations, and `{{ op_6_scope_3_ghg_emissions_from_fuel_and_energy_related_acti }}` from fuel- and energy-related activities not included in Scope 1 or Scope 2.

The annual Scope 1 and Scope 2 emissions intensity is `{{ op_6_annual_scope_1_and_2_ghg_emissions_per_person }}` per person and `{{ op_6_annual_scope_1_and_2_ghg_emissions_per_unit_of_floor_ar }}` per unit of floor area.

The baseline year for Scope 1 and Scope 2 emissions is `{{ op_6_baseline_year_for_scope_1_and_2_ghg_emissions }}`, with baseline emissions of `{{ op_6_baseline_scope_1_and_2_ghg_emissions }}`. The percentage reduction in Scope 1 and Scope 2 emissions from this baseline is `{{ op_6_percentage_reduction_in_scope_1_and_2_ghg_emissions_fro }}`. The adjusted net Scope 1 and Scope 2 emissions are `{{ op_6_adjusted_net_scope_1_and_2_ghg_emissions }}`. The university holds `{{ op_6_third_party_certified_carbon_offsets }}` of external certified carbon offsets.

The baseline year was adopted because it represents the final period of business-as-usual emissions before the global pandemic. The emissions inventory includes major greenhouse gases and is reported to both The Climate Registry and the California Air Resources Board (CARB). Scope 1 and Scope 2 inventories adhere to The Climate Registry protocol.

### Waste Performance

The annual non-hazardous waste generated is `{{ op_12_annual_non_hazardous_waste_generated }}`. The annual construction and demolition waste generated is `{{ op_12_annual_construction_and_demolition_waste_generated }}`.

Regarding waste diversion, the total non-hazardous waste diverted from disposal is `{{ op_12_total_non_hazardous_waste_diverted_from_disposal }}`. This includes `{{ op_12_non_hazardous_waste_recycled }}` recycled, `{{ op_12_non_hazardous_waste_composted }}` composted, and `{{ op_12_non_hazardous_waste_prepared_for_reuse }}` prepared for reuse. The total construction and demolition waste diverted from disposal is `{{ op_12_total_construction_and_demolition_waste_diverted_from }}`. This consists of `{{ op_12_construction_and_demolition_waste_recycled }}` recycled and `{{ op_12_construction_and_demolition_waste_prepared_for_reuse }}` prepared for reuse.

Waste directed to disposal includes `{{ op_12_non_hazardous_waste_disposed_of_to_a_landfill_or_incin }}` of non-hazardous waste disposed of to a landfill or incinerator, and `{{ op_12_construction_and_demolition_waste_disposed_of_to_a_lan }}` of construction and demolition waste disposed of to a landfill or incinerator.

The university operates a surplus programme to store, sell, donate, or reuse institution-owned items. It also participates in a reuse programme for personal items. Composting is integrated into campus collection systems and processed at an industrial composting facility. The university has eliminated certain single-use disposable plastics and maintains a hazardous waste management programme to minimise hazardous material use.

### Supplier Environmental Assessment

The percentage of bid solicitations that identify supplier sustainability considerations is `{{ op_9_percentage_of_bid_solicitations_that_identify_supplier }}`. The supplier code of conduct includes environmental expectations that exceed regulatory compliance.

### Data Limitations and Gaps

Several reporting limitations exist when mapping the available data to GRI standards:

- **Energy (GRI 302):** GRI 302-1 requires energy values in joules, whereas the source data is reported in megawatt-hours. A conversion factor must be applied. The renewable energy consumption field includes renewable electricity, which is broader than the renewable fuel scope of Disclosure 302-1-b; the precise renewable fuel figure is represented by renewable stationary fuels. Heating oil and coal/coke are reported as nil, representing a complete absence of consumption rather than missing data. The denominators for energy intensity ratios are the combined full-time equivalent of students and employees, and the gross floor area. GRI 302-2, GRI 302-4, and GRI 302-5 are not reported.
- **Water (GRI 303):** GRI 303-3 requires water volumes in megalitres, whereas the source data is in cubic metres. On-site abstraction is reported as nil, meaning off-site potable water represents the entire withdrawal. The volume of harvested rainwater is not quantified. GRI 303-1 is limited to a risk grade for the main campus and does not describe wider stakeholder interactions or multi-campus impacts. GRI 303-2 is not reported.
- **Emissions (GRI 305):** The baseline year and baseline emissions are reported as a combined Scope 1 and Scope 2 total, which cannot be split to satisfy Disclosure 305-1 and Disclosure 305-2 separately. The source of emission factors, global warming potential rates, and the consolidation approach are not reported. The percentage reduction is net of purchased offsets; the gross reduction differs because the university holds offsets. GRI 305-5-b and Disclosure 305-5-d remain unallocated by scope or gas. Biogenic emissions are reported as CO2-equivalent, which may differ from the biogenic CO2 boundary. Specific Scope 1, Scope 2, and Scope 3 categories (such as capital goods and purchased goods) were left blank. GRI 305-6 and GRI 305-7 are not reported.
- **Waste (GRI 306):** Hazardous waste is not quantified by weight, meaning total waste generation under Disclosure 306-3 and diversion under Disclosure 306-4 cannot be fully reported. Disclosure 306-4-d requires a split of recovery operations into on-site and off-site, which is not collected. Disclosure 306-5 requires a split of disposal across multiple operations, but the source data merges landfill and incineration. GRI 306-1 is not reported.
- **Suppliers (GRI 308):** GRI 308-1 requires the percentage of new suppliers screened, whereas the source data reports the percentage of bid solicitations. GRI 308-2 is not reported.
- **Materials (GRI 301):** GRI 301-1, GRI 301-2, and GRI 301-3 are not reported as the university does not manufacture physical products.