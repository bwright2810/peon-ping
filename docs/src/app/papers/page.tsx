import type { Metadata } from "next";
import { getAllPosts } from "@/lib/posts";
import { PostCard } from "@/components/blog/PostCard";

export const metadata: Metadata = {
  title: "PeonPapers — peon-ping",
  description:
    "Technical dispatches from the goldmine. Architecture decisions, engineering deep dives, and opinions — all reviewed by the war room.",
  openGraph: {
    title: "PeonPapers — peon-ping",
    description:
      "Technical dispatches from the goldmine. Architecture decisions, engineering deep dives, and opinions.",
    type: "website",
    url: "https://peonping.com/papers",
    images: ["https://peonping.com/images/og-image.png"],
  },
  twitter: {
    card: "summary_large_image",
    title: "PeonPapers — peon-ping",
    description:
      "Technical dispatches from the goldmine. Architecture decisions, engineering deep dives, and opinions.",
    images: ["https://peonping.com/images/og-image.png"],
  },
};

export default function PapersIndex() {
  const posts = getAllPosts();

  return (
    <div>
      <div className="mb-8">
        <h1 className="font-display text-3xl text-gold">PeonPapers</h1>
        <p className="mt-2 font-body text-text-muted">
          Technical dispatches from the goldmine. Architecture decisions,
          engineering deep dives, and opinions — all reviewed by the war room.
        </p>
      </div>
      <div className="space-y-4">
        {posts.map((post) => (
          <PostCard key={post.slug} post={post} />
        ))}
      </div>
    </div>
  );
}
