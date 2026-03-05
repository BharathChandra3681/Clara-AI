# Changelog: Hendricks Fire Protection (ACC001)

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
- **Before:** `"Office Manager - Hendricks Fire Protection"`
- **After:**  `"Hendricks Fire Protection"`

### `emergency_definition` [MODIFIED]
- **Before:** `["Sprinkler discharge", "fire alarm"]`
- **After:**  `["Sprinkler discharge", "fire alarm", "sprinkler discharge", "CO alarm", "carbon monoxide", "kitchen suppression", "smoke without"]`

### `emergency_routing_rules.primary_phone` [MODIFIED]
- **Before:** `_null_`
- **After:**  `"214-555-0147"`

### `emergency_routing_rules.secondary_phone` [MODIFIED]
- **Before:** `_null_`
- **After:**  `"214-555-0193"`

### `integration_constraints` [MODIFIED]
- **Before:** `[]`
- **After:**  `["never create jobs for sprinkler calls", "never create jobs after hours, alarm calls can be auto-created during business hours only", "don't create any jobs after hours", "never auto-create ServiceTrade jobs for sprinkler-related calls, never create jobs after hours, alarm calls can be auto-created during business hours only"]`

### `office_address` [MODIFIED]
- **Before:** `_null_`
- **After:**  `"4821 Commerce Street"`

---

## Version Notes

| Version | Source | Purpose |
|---------|--------|---------|
| v1 | Demo call | Directional assumptions, preliminary configuration |
| v2 | Onboarding call | Confirmed operational rules, production-ready |

_v2 is the authoritative configuration for production deployment._