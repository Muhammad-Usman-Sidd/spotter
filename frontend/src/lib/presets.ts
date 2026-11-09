import type { DispatchPreset } from '../types/routing';

export const DISPATCH_PRESETS: readonly DispatchPreset[] = [
  {
    id: 'i80-denver-chicago',
    highway: 'I-80',
    origin: 'Denver, CO',
    destination: 'Chicago, IL',
    loadWeightLbs: 42_000,
    loadNote: 'Over 40,000 lb: wind of 35 mph or more is escalated',
  },
  {
    id: 'i90-seattle-billings',
    highway: 'I-90',
    origin: 'Seattle, WA',
    destination: 'Billings, MT',
    loadWeightLbs: 45_000,
    loadNote: 'Over 40,000 lb: wind of 35 mph or more is escalated',
  },
  {
    id: 'i40-amarillo-memphis',
    highway: 'I-40',
    origin: 'Amarillo, TX',
    destination: 'Memphis, TN',
    loadWeightLbs: 28_000,
    loadNote: 'Under 30,000 lb: no wind load escalation',
  },
];
