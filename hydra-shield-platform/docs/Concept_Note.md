# Talaix: From Satellite to Soil – A Digital Twin for Preemptive Fuel-Moisture Management to Reduce Wildfire Risk in WUI Communities

## 1. Project Overview
- **Project Name:** Talaix
- **Theme:** Climate Adaptation, Disaster Risk Reduction, Earth Observation (EO), DeepTech.
- **Target Funding Streams:** Copernicus Incubation, CASSINI, Cascade Funding (FSTP - Phase 1: Digital PoC).

### Copernicus / EU Policy Compliance Mapping
| **EU Priority** | **Talaix Contribution** |
|-----------------|------------------------------|
| **Copernicus User Uptake** | Uses Sentinel‑2/3 + EMS/EFFIS to produce actionable protection blueprints. |
| **Copernicus Climate Change Service (C3S)** | Uses ECMWF data and directly supports localized climate adaptation. |
| **EU Mission on Adaptation** | Reduces wildfire propagation risk for vulnerable WUI communities. |
| **EU Forest Strategy 2030** | Supports the resilience pillar via preemptive moisture corridors. |
| **CASSINI Space Entrepreneurship** | Provides an EO-driven SaaS decision-support tool for municipalities. |
| **Sendai Framework (Target E)** | Offers actionable, anticipatory disaster risk-reduction strategies. |

## 2. Executive Summary & Core Hypothesis
Wildfires are becoming increasingly devastating, threatening vulnerable Wildland-Urban Interface (WUI) communities across the globe. Talaix is designed as a complementary preventive infrastructure, not a replacement for conventional firefighting. It is an AI-driven adaptive wildfire risk reduction system that uses Earth Observation (EO) to identify where and when targeted subsurface fuel-moisture management can create protective corridors around vulnerable communities. 

**Strategic Focus (Life-First Shielding):** The primary focus of Talaix is on "High-Consequence WUI Zones"—regions where severe fire risk intersects with civilian entrapment potential (e.g., single-access roads). The system aims to secure safe evacuation corridors and delay fire progression to residential thresholds. *Note: Talaix may contribute to safer evacuation corridors, but it does not replace evacuation planning, traffic management, public warning systems, or civil protection decision-making.*

**The Core Scientific Hypothesis:** Talaix hypothesizes that, under defined soil, fuel, and fire-weather conditions, strategically increasing moisture in combustible fuel layers before fire arrival can reduce ignition probability and/or fire-spread rate sufficiently to create a measurable protective effect. The project will determine the minimum effective moisture increase, intervention area, water volume, and lead time required, rather than assuming these parameters a priori.

**Scientific Evidence Supporting the Hypothesis:**
The hypothesis is rooted in established wildfire science (e.g., NFDRS, Scott & Burgan fuel models). Indicative literature suggests that meaningful increases in Fuel Moisture Content (FMC) may reduce the Rate of Spread (ROS) under certain Mediterranean fuel and weather scenarios. Phase 1 will quantify these relationships for selected fuel models and testbeds, rather than assuming a universal response. Furthermore, EO indices (NDMI, NDWI) are proven proxies for assessing baseline FMC. Phase 1 will explicitly model the capillary transfer linking subsurface soil moisture to critical surface litter moisture (The Soil-to-Fuel Moisture Transfer Problem).

**Unique Value Proposition (UVP):** Talaix is designed to provide an Actionable Protection Blueprint that translates EO-derived wildfire risk information into a spatially and temporally optimized water-management strategy, designed for interoperability with Copernicus EMS/EFFIS and existing civil-protection workflows.

### Competitive Advantage Matrix
| Feature | Talaix | Standard Operational Civil Protection Tools |
|---------|-------------|---------------------------------------------|
| Delivers actionable execution blueprint | ✅ Yes | ❌ No (Stops at risk mapping) |
| Dynamically manages water consumption | ✅ Yes | ❌ No (Static or massive volume) |
| Simulates subsurface-to-surface moisture transfer | ✅ Yes | ❌ No |
| Operates in Water-Scarce resource allocation modes | ✅ Yes | ❌ No |
| Interoperable with Civil Protection (Copernicus EMS) | ✅ Yes | ❌ Rarely |
| Quantifies Water-Use Efficiency Ratio (WUER) | ✅ Yes | ❌ No |

## 3. Mathematical Model Overview
Talaix relies on rigorous mathematical foundations to optimize resources. Key equations targeted in Phase 1 include:
1. **Water-Use Efficiency Ratio:** `WUER = (Risk_baseline - Risk_Talaix) / Volume of water applied`
2. **Minimum Effective FMC Increase:** `MEFMI = FMC_target - FMC_baseline`
3. **Probability of Spread:** `P_spread(t) = f(FMC, wind, slope, fuel type)`
4. **Reduced Rate of Spread:** `ROS_reduced = ROS_baseline × R_FMC(MEFMI, fuel type, weather, slope)` *(where R_FMC is a calibrated, non-linear reduction factor bounded between 0 and 1)*
5. **Critical Area Optimization:** `A_critical = min(A) subject to P_spread(t) ≤ θ, V ≤ V_available, and t_lead ≥ t_min`

## 4. The 5-Layer Adaptive Closed-Loop Architecture
Talaix operates as a continuous closed-loop decision-support system with a strict **Human-in-the-Loop Decision Gate**:
*The AI generates a traffic-light recommendation for each protection zone:*
- 🟢 **Green (Deploy):** High confidence, low uncertainty → authorized operator approval.
- 🟡 **Yellow (Review):** Moderate uncertainty → operator reviews additional model outputs before deciding.
- 🔴 **Red (Hold):** High uncertainty or conflicting data → operator overrides or requests manual reassessment.
*(A configurable human decision window will be maintained between model recommendation and physical activation, according to operational requirements.)*

1. **Earth Observation Layer:** Ingests Copernicus Sentinel-2/3, DEM data, and real-time weather (ECMWF/Meteosat). **Cloud Cover Mitigation:** To address Sentinel-2 cloud cover limitations, Phase 1 implements a data fusion pipeline using Sentinel-1 SAR (subject to calibration in densely vegetated areas) and ECMWF soil moisture reanalysis (ERA5-Land) for temporal interpolation.
2. **Fire Risk & Spread Prediction:** Combines Machine Learning with established landscape-scale physics-based wildfire spread models.
3. **Protection Optimisation (Water-Scarce Mode):** Calculates the Critical Protection Zone. In Water-Scarce mode, the AI optimizes **resource allocation**, prioritizing the protection of critical infrastructure (hospitals, schools) and **securing single-access evacuation routes** under strict water constraints.
4. **Adaptive Water Intervention Planning:** Determines *where, when, and how much* water to deploy. **Interoperability with Early Warning Systems:** Talaix's outputs (lead times and protection zones) are designed to be machine-readable and interoperable with existing early-warning dissemination platforms (e.g., EU CECIS), enabling synchronized public alerts.
5. **Verification & Feedback:** In Phase 1, verification is performed through historical hindcasting using historical burned-area observations from EFFIS. 

## 5. Water Savings Quantification & KPIs
**Water Savings Quantification:** Conventional aerial firefighting can be water-intensive, and a portion of dropped water may be lost to evaporation, drift, or runoff. Talaix will investigate whether targeted subsurface hydration can achieve a comparable or greater reduction in fire propagation risk using lower water volumes applied over longer lead times. Subsurface hydration is expected to substantially reduce direct evaporative loss compared with surface application, although soil evaporation, transpiration, and system losses may still occur. Phase 1 will explicitly quantify these potential savings via the digital twin.

**Phase 1 Success Criteria (KPIs):**
1. **Validation / Hindcasting:** Model validation will use at least three historical fire events. Metrics may include AUC, Critical Success Index, precision/recall, and spatial overlap.
2. **WUER Quantification:** Quantify risk reduction (e.g., burned area reduction) per cubic meter of water compared to a static-buffer baseline.
3. **MEFMI Definition:** Determine the fuel-specific and scenario-dependent minimum effective FMC increase required to statistically reduce propagation.
4. **Lead Time Feasibility:** Determine whether the required moisture-transfer lead time falls within an actionable operational window (e.g., 6-24 hours).
5. **Societal KPI (Evacuation Safety Margin - ESM):** `ESM = t_evacuation_window - t_fire_arrival - t_operational_margin - t_uncertainty` *(where t_uncertainty is an additional safety buffer reflecting fire arrival prediction confidence)*. Talaix aims to improve ESM by delaying fire progression toward residential thresholds.
6. **Economic KPI (EAL):** Estimate potential changes in Expected Annual Loss (EAL) under baseline and intervention scenarios.

## 6. Phase 1: Digital Feasibility & Scientific Validation (Current Request)
**Funding Target:** €50,000 - €100,000 | **Duration:** 9 Months

**Work Packages (WP) & Timeline:**
| Month | WP1 | WP2 | WP3 | WP4 | WP5 | WP6 | Key Deliverables |
|-------|-----|-----|-----|-----|-----|-----|-------------------|
| M1 | ✅ | | | | | | D1.1 (Testbed Selection & Baseline Risk Report) |
| M2 | ✅ | ✅ | | | | | |
| M3 | | ✅ | ✅ | | | | |
| M4 | | | ✅ | ✅ | | | |
| M5 | | | | ✅ | ✅ | | D1.2 (Digital Twin prototype on restricted repo) |
| M6 | | | | | ✅ | ✅ | |
| M7 | | | | | | ✅ | D1.3 (Dynamic Decision Matrix) |
| M8 | | | | | | ✅ | |
| M9 | | | | | | ✅ | D1.4 (Final White Paper & IP Strategy) |

## 7. Budget Breakdown & Team Expertise
| Category | Allocation | Details |
|----------|------------|---------|
| Personnel (AI/GIS, Soil Physicist, Fire Modeler) | 52% | Core scientific and technical staff |
| Cloud Computing & HPC Simulations | 13% | AWS/Azure scenario modeling |
| Ancillary Data & Processing Services | 10% | High-res commercial topography/weather APIs |
| Dissemination & Open-Source Docs | 5% | GitHub release prep, white paper preparation |
| Project Management, Stakeholder & IP/Legal | 20% | User Advisory Board, Patentability/IP assessment |

**Phase 1 Team:** The consortium will include expertise in EO data processing, wildfire modelling, soil physics, AI/ML, GIS, and project management, alongside civil protection stakeholder advisors.

## 8. Deployment Scenarios, Ethics, and Sustainability
**Deployment Scenarios:** Phase 1 will simulate interventions across distinct topologies in one primary European WUI testbed:
1. *Small Mediterranean Village (High-Consequence):* Concentrated WUI with single-road access and limited water.
2. *Mountainous WUI:* High-slope terrain focusing on downslope and flanking fire progression under wind-driven scenarios.
3. *Sandy Soil Region:* Testing rapid drainage and limited capillary rise (evaluating hybrid surface wetting fallback).
4. *Urban Fringe Scenario:* Protecting city outskirts containing highly flammable green spaces.

**Ethical & Environmental Considerations:**
Talaix will incorporate known environmental and regulatory constraints into the optimisation model. Where data are available, the system will avoid designated protected ecological reserves, sensitive aquifers, and drinking-water sources. Physical deployment (Phase 2) will be subject to environmental assessment, water-use permits, and local regulations.

**Risk Assessment (Operational/Adoption):** Civil protection agencies may be hesitant to adopt AI-driven recommendations. *Mitigation:* A User Advisory Board will be engaged from Month 1, and recommendations will feature visual explainability (e.g., SHAP-based feature importance maps) to build institutional trust. If subsurface-only hydration is insufficient, Phase 1 will evaluate a **Hybrid Scenario** (subsurface + short-notice surface wetting) as a complementary concept.

**Sustainability, IP & Dissemination:** 
- **Academic Dissemination:** Submission of at least one peer-reviewed scientific manuscript and presentation at relevant scientific conferences, *subject to IP and confidentiality review*.
- **IP Strategy:** An IP review and patentability assessment will be conducted before any public disclosure of protectable elements. If patentability is confirmed, a priority filing will be made before open-source release or academic publication. Alternative protections (trade secrets, copyright) will also be assessed.
- **Phase 2-3 Business Model:** Post field-validation, Talaix will offer a SaaS model for municipalities (annual subscription for AI risk maps and hydration recommendations). Revenue streams target B2G (civil protection) and B2B (insurance underwriters).
- **Stakeholder Engagement:** A **User Advisory Board** of municipal civil protection agencies will co-define risk thresholds and provide feedback to secure Letters of Intent for Phase 2 field prototypes.
