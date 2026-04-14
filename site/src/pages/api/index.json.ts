import type { APIRoute } from 'astro';
import { getAllSessions } from '../../lib/data';

export const GET: APIRoute = () => {
  const sessions = getAllSessions().map(s => ({
    chamber: s.chamber,
    session_id: s.session_id,
    date: s.date,
    committee: s.committee,
    duration: s.duration,
    speaker_count: s.speakers.length,
    source_url: s.source_url,
  }));
  return new Response(JSON.stringify(sessions), {
    headers: { 'Content-Type': 'application/json' },
  });
};
