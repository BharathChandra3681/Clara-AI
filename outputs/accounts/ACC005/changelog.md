# Changelog: Sternfeld Mechanical (ACC005)

**Generated:** 2026-03-05 07:52 UTC  
**Change:** v1 (Demo-derived) → v2 (Onboarding-confirmed)

---

## Summary

- **Total changes:** 6
- **Added fields:** 0
- **Modified fields:** 6
- **Removed fields:** 0

---

## Field-Level Changes

### `company_name` [MODIFIED]
- **Before:** `"Owner - Sternfeld Mechanical"`
- **After:**  `"Sternfeld Mechanical"`

### `emergency_definition` [MODIFIED]
- **Before:** `["Gas leak", "Active water", "Boiler failure", "Sewage backup"]`
- **After:**  `["Gas leak", "Active water", "Boiler failure", "Sewage backup", "water main break", "boiler failure", "sewage backup", "pipe burst"]`

### `emergency_routing_rules.primary_contact` [MODIFIED]
- **Before:** `_null_`
- **After:**  `"Eddie Garza"`

### `emergency_routing_rules.primary_phone` [MODIFIED]
- **Before:** `_null_`
- **After:**  `"720-555-0416"`

### `emergency_routing_rules.secondary_phone` [MODIFIED]
- **Before:** `_null_`
- **After:**  `"720-555-0288"`

### `integration_constraints` [MODIFIED]
- **Before:** `[]`
- **After:**  `["never create job records in ServiceTrade", "no job creation under any circumstance"]`

---

## Version Notes

| Version | Source | Purpose |
|---------|--------|---------|
| v1 | Demo call | Directional assumptions, preliminary configuration |
| v2 | Onboarding call | Confirmed operational rules, production-ready |

_v2 is the authoritative configuration for production deployment._