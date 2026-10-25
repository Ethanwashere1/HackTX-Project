/** Removable SerpAPI-shaped demo payloads (used when VITE_USE_MOCKS=1). */

export type EnrichmentPlace = {
  title: string;
  address?: string;
  rating?: number;
  type?: string;
  maps_url?: string;
};

export type EnrichmentEvent = {
  title: string;
  date?: string;
  venue?: string;
  link?: string;
};

export type EnrichmentSocial = {
  kind: string;
  handle: string;
  display_name?: string;
  bio?: string;
  profile_url?: string;
  notes?: string;
};

export type EnrichmentContext = {
  location: {
    lat: number | null;
    lng: number | null;
    label: string;
    fallback_lat: number;
    fallback_lng: number;
  };
  maps: { source: string; engine: string; results: EnrichmentPlace[] };
  calendar: { source: string; engine: string; results: EnrichmentEvent[] };
  social: { source: string; engine: string; result: EnrichmentSocial };
  serpapi_configured: boolean;
};

export const demoEnrichment: EnrichmentContext = {
  location: {
    lat: null,
    lng: null,
    label: "Default · UT Austin campus",
    fallback_lat: 30.2849,
    fallback_lng: -97.7341,
  },
  maps: {
    source: "demo_fallback",
    engine: "google_maps",
    results: [
      {
        title: "PCL (Perry-Castañeda Library)",
        address: "101 E 21st St, Austin, TX",
        rating: 4.6,
        type: "library",
        maps_url: "https://maps.google.com/?q=Perry-Castaneda+Library",
      },
      {
        title: "GDC (Gates Dell Complex)",
        address: "2317 Speedway, Austin, TX",
        rating: 4.7,
        type: "university",
        maps_url: "https://maps.google.com/?q=Gates+Dell+Complex",
      },
      {
        title: "Spider House Cafe",
        address: "2908 Fruth St, Austin, TX",
        rating: 4.5,
        type: "cafe",
        maps_url: "https://maps.google.com/?q=Spider+House+Cafe",
      },
    ],
  },
  calendar: {
    source: "demo_fallback",
    engine: "google_events",
    results: [
      {
        title: "HackTX Opening Ceremony",
        date: "Sat, Oct 25 · 10:00 AM",
        venue: "GDC Auditorium",
        link: "https://hacktx.com",
      },
      {
        title: "UTCS Career Fair",
        date: "Tue, Oct 28 · 1:00 PM",
        venue: "PCL",
        link: "https://www.cs.utexas.edu",
      },
      {
        title: "Campus photo walk meetup",
        date: "Sun, Oct 27 · 5:30 PM",
        venue: "Main Mall",
        link: "https://maps.google.com/?q=UT+Austin+Main+Mall",
      },
    ],
  },
  social: {
    source: "demo_fallback",
    engine: "google",
    result: {
      kind: "github",
      handle: "mayachen",
      display_name: "Maya Chen",
      bio: "Builder · UT Austin · open to HackTX squads",
      profile_url: "https://github.com/mayachen",
      notes: "Public profile signals: React, campus tools, climate apps.",
    },
  },
  serpapi_configured: false,
};
