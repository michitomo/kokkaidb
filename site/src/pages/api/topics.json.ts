import type { APIRoute } from 'astro';
import { getAllSessions, getSessionData, sessionSlug } from '../../lib/data';

export const GET: APIRoute = () => {
  const sessions = getAllSessions();
  const allTopics: Array<{
    name: string;
    description: string;
    session_id: string;
    chamber: string;
    date: string;
    committee: string;
  }> = [];

  for (const session of sessions) {
    try {
      const [year, month, day] = session.date.split('-');
      const slug = sessionSlug(session);
      const { topics } = getSessionData(session.chamber, year, month, day, slug);
      for (const topic of topics.topics) {
        allTopics.push({
          name: topic.name,
          description: topic.description,
          session_id: session.session_id,
          chamber: session.chamber,
          date: session.date,
          committee: session.committee,
        });
      }
    } catch {
      // topics.json が存在しないセッションはスキップ
    }
  }

  return new Response(JSON.stringify(allTopics), {
    headers: { 'Content-Type': 'application/json' },
  });
};
