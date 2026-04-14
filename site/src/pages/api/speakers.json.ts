import type { APIRoute } from 'astro';
import { getAllSessions } from '../../lib/data';

export const GET: APIRoute = () => {
  const sessions = getAllSessions();
  // 全セッション横断で発言者を収集（重複なし、名前をキーに集約）
  const speakerMap = new Map<string, {
    name: string;
    affiliation: string;
    session_count: number;
  }>();

  for (const session of sessions) {
    for (const speaker of session.speakers) {
      const existing = speakerMap.get(speaker.name);
      if (existing) {
        existing.session_count += 1;
      } else {
        speakerMap.set(speaker.name, {
          name: speaker.name,
          affiliation: speaker.affiliation,
          session_count: 1,
        });
      }
    }
  }

  const speakers = Array.from(speakerMap.values()).sort(
    (a, b) => b.session_count - a.session_count
  );

  return new Response(JSON.stringify(speakers), {
    headers: { 'Content-Type': 'application/json' },
  });
};
