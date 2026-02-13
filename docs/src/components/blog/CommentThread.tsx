import { type PostComment } from "@/data/characters";
import { CharacterComment } from "./CharacterComment";

export function CommentThread({ comments }: { comments: PostComment[] }) {
  if (!comments.length) return null;

  return (
    <section className="mt-12">
      <div className="mb-6 flex items-center gap-3">
        <div className="h-px flex-1 bg-card-border" />
        <h2 className="font-display text-xl text-gold">
          War Room Discussion
        </h2>
        <div className="h-px flex-1 bg-card-border" />
      </div>
      <div className="space-y-3">
        {comments.map((comment, i) => (
          <CharacterComment key={i} comment={comment} />
        ))}
      </div>
      <div className="mt-6 flex justify-center">
        <a
          href="https://discord.gg/guEDn2Umen"
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-2 rounded-lg border border-gold/30 bg-gold/10 px-5 py-3 font-display text-sm text-gold transition-colors hover:bg-gold/20"
        >
          <svg width="20" height="16" viewBox="0 0 71 55" fill="currentColor" xmlns="http://www.w3.org/2000/svg">
            <path d="M60.1 4.9A58.5 58.5 0 0045.4.2a.2.2 0 00-.2.1 40.8 40.8 0 00-1.8 3.7 54 54 0 00-16.2 0A37.4 37.4 0 0025.4.3a.2.2 0 00-.2-.1 58.4 58.4 0 00-14.7 4.6.2.2 0 00-.1.1C1.5 18.7-.9 32 .3 45.1v.2a58.9 58.9 0 0017.8 9 .2.2 0 00.3-.1 42.2 42.2 0 003.6-5.9.2.2 0 00-.1-.3 38.8 38.8 0 01-5.5-2.7.2.2 0 01 0-.4l1.1-.9a.2.2 0 01.2 0 42 42 0 0035.8 0 .2.2 0 01.2 0l1.1.9a.2.2 0 010 .4 36.4 36.4 0 01-5.5 2.7.2.2 0 00-.1.3 47.4 47.4 0 003.6 5.9.2.2 0 00.3.1 58.7 58.7 0 0017.9-9 .2.2 0 00.1-.2c1.4-15-2.3-28-9.9-39.6a.2.2 0 00-.1-.1zM23.7 37c-3.4 0-6.3-3.2-6.3-7s2.8-7 6.3-7 6.3 3.1 6.3 7-2.8 7-6.3 7zm23.3 0c-3.4 0-6.3-3.2-6.3-7s2.8-7 6.3-7 6.4 3.1 6.3 7-2.8 7-6.3 7z"/>
          </svg>
          Join the Discussion
        </a>
      </div>
    </section>
  );
}
