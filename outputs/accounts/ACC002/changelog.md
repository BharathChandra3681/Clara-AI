# Changelog: ArcticPro HVAC Services (ACC002)

**Generated:** 2026-03-05 07:52 UTC  
**Change:** v1 (Demo-derived) → v2 (Onboarding-confirmed)

---

## Summary

- **Total changes:** 7
- **Added fields:** 0
- **Modified fields:** 7
- **Removed fields:** 0

---

## Field-Level Changes

### `company_name` [MODIFIED]
- **Before:** `"Owner - ArcticPro HVAC Services"`
- **After:**  `"ArcticPro HVAC Services"`

### `emergency_definition` [MODIFIED]
- **Before:** `["Carbon monoxide", "system failure"]`
- **After:**  `["Carbon monoxide", "system failure", "CO alarm", "active water"]`

### `emergency_routing_rules.primary_contact` [MODIFIED]
- **Before:** `_null_`
- **After:**  `"Tony Reyes"`

### `emergency_routing_rules.primary_phone` [MODIFIED]
- **Before:** `_null_`
- **After:**  `"602-555-0214"`

### `emergency_routing_rules.secondary_contact` [MODIFIED]
- **Before:** `_null_`
- **After:**  `"Marcus Webb"`

### `emergency_routing_rules.secondary_phone` [MODIFIED]
- **Before:** `_null_`
- **After:**  `"602-555-0388"`

### `integration_constraints` [MODIFIED]
- **Before:** `["Don't create a duplicate"]`
- **After:**  `["Don't create a duplicate", "Do not create a new job record during the call, we do that manually"]`

---

## Version Notes

| Version | Source | Purpose |
|---------|--------|---------|
| v1 | Demo call | Directional assumptions, preliminary configuration |
| v2 | Onboarding call | Confirmed operational rules, production-ready |

_v2 is the authoritative configuration for production deployment._