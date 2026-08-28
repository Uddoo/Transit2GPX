# Journey editor design QA

## Comparison target

- Source visual truth: `/Users/liyiwei/.codex/generated_images/01a02465-24d3-7bc3-ba75-1ea324e6ed08/exec-6a35cfe9-8cd3-45b3-81f9-6b34cab7f7b5.png`
- Implementation screenshot: `/private/tmp/metro2fog-journey-final-desktop-settled.png`
- Desktop viewport and CSS size: 1488 × 1058
- Source pixels: 1488 × 1058; implementation pixels: 1488 × 1058; device scale factor: 1; no density normalization required.
- State: `/journeys/new`, metro mode, real local data loaded, a route preview generated and candidate actions visible.
- Browser evidence: local Chromium capture. The in-app browser was unavailable; the user explicitly allowed the Playwright screenshot fallback.
- Responsive evidence: `/private/tmp/metro2fog-journey-final-mobile.png` at 390 × 844 CSS px / device scale factor 1.

## Full-view and focused comparison

The source and settled desktop render were opened together at the same 1488 × 1058 viewport. The full view verifies the horizontal navigation, status strip, left editing rail, dominant map, and attached candidate/action bar. The left form, map controls, and candidate strip remain readable at this scale, so no separate cropped comparison was needed.

## Comparison history

### Iteration 1

**Findings**

- [P2] Candidate bar was initially pushed below the first viewport because advanced route controls consumed the left-form height.
  - Evidence: the first route-preview capture clipped the action row.
  - Fix: moved direction and via-station controls into a collapsed “更多路线选项” disclosure that automatically opens for automatic-transfer mode; reduced only the visual spacing of the metro form.

- [P2] Candidate summary capture was still mid-entry animation, making its text and buttons appear faded.
  - Evidence: the first post-preview capture was taken while the reveal transition was running.
  - Fix: captured the settled preview state after the transition; the candidate strip now has a high-contrast heading, labeled metrics, black export action, and outlined secondary actions.

### Final pass

**Findings**

- No actionable P0/P1/P2 fidelity findings remain.

Required fidelity surfaces checked:

- Typography: black display-weight journey title, compact navigation labels, and restrained utility labels preserve the source hierarchy without clipped or wrapped primary text.
- Spacing and layout rhythm: the top navigation/status bands, two-column editor, map frame, and full-width results bar follow the selected composition; the candidate actions remain inside the desktop viewport.
- Colors and tokens: true white canvas, black primary actions, grayscale input fills, thin neutral dividers, and teal limited to route/data state align with the selected Uber-influenced direction.
- Image and asset fidelity: the implementation uses the existing real Leaflet map and project icon system; no fabricated raster or placeholder artwork replaces a referenced asset.
- Copy and content: the active workflow labels, metro/rail tabs, form controls, path preview, candidate metrics, and save/export actions are code-native and reflect the current application state.

## Interaction coverage

- Metro line options are naturally sorted by Chinese line name with numeric ordering (`2号线`, `6号线`, `10号线`).
- Preview, candidate selection, save, direct GPX export, map station selection, automatic-transfer via station selection, desktop navigation, and mobile navigation passed the automated regressions.
- Lint, unit tests, production build, and all 20 Playwright desktop/mobile smoke tests passed.

## Follow-up polish

- [P3] The real OpenStreetMap tile styling naturally carries more geographic detail than the concept map; its grayscale/saturation treatment keeps the candidate route dominant without obscuring real map data.

final result: passed

---

# Railway / high-speed tab follow-up QA

## Comparison target

- Source visual truth: `/Users/liyiwei/.codex/generated_images/01a02465-24d3-7bc3-ba75-1ea324e6ed08/exec-6a35cfe9-8cd3-45b3-81f9-6b34cab7f7b5.png`
- Implementation screenshot: `/private/tmp/metro2fog-rail-desktop-after.png`
- Desktop viewport: 1490 × 980 CSS px / device scale factor 1; source: 1487 × 1058 px. The comparison uses the shared first-viewport shell rather than scaled pixels.
- State: `/journeys/new` → `铁路 / 高铁`; the local rail sidecar is not enabled, so the railway-specific readiness message is intentionally visible while the factual form remains usable.
- Responsive evidence: `/private/tmp/metro2fog-rail-mobile-current.png` at 390 × 844 CSS px / device scale factor 1.
- Capture method: local Chromium. The in-app Browser runtime had no available browser; the user had explicitly authorized the Playwright fallback.

## Final pass

The source and railway implementation screenshots were opened together. No actionable P0/P1/P2 fidelity findings remain.

Checked comparison points:

- Horizontal navigation, status strip, white canvas, and thin neutral separators match the selected shared shell.
- The railway heading and metro/rail tabs now live in the same left editing rail as the metro flow; the active tab is black and inactive tab stays outlined.
- Input controls use the same gray fills, strong label treatment, rounded geometry, and black primary-action hierarchy.
- The map is the dominant right-side canvas, including the shared grayscale tile treatment and elevated zoom controls.
- Railway candidate results are now a full-width bottom bar; save-and-export is black while return/save actions are outlined.
- Selected railway geometry/endpoints use teal; non-selected candidate routes are intentionally gray so route data remains the only accent color.
- At mobile width, the rail workspace switches to a vertical document flow without horizontal overflow; title, tabs, fact controls, map, and candidate section remain reachable by scrolling.

Interaction coverage: the railway tab, editable unavailable-data state, station search, railway path preview, candidate selection, save, export, and mobile flow are covered by the existing automated suite. Lint, 9 unit tests, production build, and 20 desktop/mobile Playwright smoke tests passed.

Intentional deviation: the real application’s rail-unavailable notice and real geographic map data replace the source’s ready-data route preview only when the local sidecar is not running; this preserves the product’s actual state rather than hiding it with a fictitious route.

final result: passed
