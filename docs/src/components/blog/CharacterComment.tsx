import { characters, type PostComment } from "@/data/characters";

export function CharacterComment({ comment }: { comment: PostComment }) {
  const char = characters[comment.characterId];
  if (!char) return null;

  return (
    <div className="flex gap-3 rounded-lg border border-card-border bg-card-bg p-4">
      <div className="shrink-0">
        <img
          src={char.avatar}
          alt={char.name}
          className="h-12 w-12 rounded-full border-2 object-cover"
          style={{ borderColor: char.color }}
        />
      </div>
      <div className="min-w-0 flex-1">
        <div className="mb-1 flex flex-wrap items-center gap-2">
          <span className="font-body text-sm font-semibold text-text-primary">
            {char.name}
          </span>
          <span
            className="rounded px-1.5 py-0.5 text-xs font-medium"
            style={{
              backgroundColor: char.color + "22",
              color: char.color,
            }}
          >
            {char.faction}
          </span>
          <span className="text-xs text-text-dim">{char.game}</span>
        </div>
        <p className="font-body text-sm leading-relaxed text-text-body">
          {comment.text}
        </p>
        <span className="mt-2 block text-xs text-text-dim">
          {comment.timestamp}
        </span>
      </div>
    </div>
  );
}
