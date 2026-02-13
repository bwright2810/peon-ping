import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { MDXRemote } from "next-mdx-remote/rsc";
import { getAllPosts, getPostBySlug } from "@/lib/posts";
import { postComments } from "@/data/characters";
import { CommentThread } from "@/components/blog/CommentThread";

export function generateStaticParams() {
  return getAllPosts().map((post) => ({ slug: post.slug }));
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string }>;
}): Promise<Metadata> {
  const { slug } = await params;
  let post;
  try {
    post = getPostBySlug(slug);
  } catch {
    return {};
  }

  const { title, description, heroImage } = post.meta;
  const ogImage = heroImage
    ? `https://peonping.com${heroImage}`
    : "https://peonping.com/images/og-image.png";

  return {
    title: `${title} — peon-ping`,
    description,
    openGraph: {
      title,
      description,
      type: "article",
      url: `https://peonping.com/papers/${slug}`,
      images: [ogImage],
    },
    twitter: {
      card: "summary_large_image",
      title,
      description,
      images: [ogImage],
    },
  };
}

export default async function PostPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;

  let post;
  try {
    post = getPostBySlug(slug);
  } catch {
    notFound();
  }

  const comments = postComments[slug] || [];

  return (
    <article>
      <header className="mb-8">
        <h1 className="font-display text-3xl leading-tight text-gold">
          {post.meta.title}
        </h1>
        <div className="mt-3 flex items-center gap-2 text-sm text-text-dim">
          <span>{post.meta.author}</span>
          <span>&middot;</span>
          <span>{post.meta.date}</span>
        </div>
      </header>

      <div className="prose-peon">
        <MDXRemote source={post.content} />
      </div>

      <CommentThread comments={comments} />
    </article>
  );
}
