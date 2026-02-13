import Link from "next/link";
import type { PostMeta } from "@/lib/posts";

export function PostCard({ post }: { post: PostMeta }) {
  return (
    <Link
      href={`/papers/${post.slug}`}
      className="group block rounded-lg border border-card-border bg-card-bg p-6 transition-colors hover:border-gold/40"
    >
      {post.heroImage && (
        <img
          src={post.heroImage}
          alt=""
          className="mb-4 h-48 w-full rounded object-cover"
        />
      )}
      <h2 className="font-display text-lg text-text-primary transition-colors group-hover:text-gold">
        {post.title}
      </h2>
      <p className="mt-2 font-body text-sm leading-relaxed text-text-muted">
        {post.description}
      </p>
      <div className="mt-4 flex items-center gap-2 text-xs text-text-dim">
        <span>{post.author}</span>
        <span>&middot;</span>
        <span>{post.date}</span>
      </div>
    </Link>
  );
}
