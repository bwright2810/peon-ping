import Link from "next/link";

export default function PapersLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="min-h-screen bg-surface-bg">
      <header className="border-b border-card-border bg-card-bg/80 backdrop-blur-sm">
        <div className="mx-auto flex max-w-3xl items-center justify-between px-6 py-4">
          <Link
            href="/"
            className="flex items-center gap-2 text-text-muted transition-colors hover:text-text-primary"
          >
            <img
              src="/images/peon-icon.png"
              alt="peon-ping"
              className="h-8 w-8"
            />
            <span className="font-body text-sm">peon-ping</span>
          </Link>
          <Link href="/papers" className="font-display text-xl text-gold">
            PeonPapers
          </Link>
        </div>
      </header>
      <main className="mx-auto max-w-3xl px-6 py-10">{children}</main>
    </div>
  );
}
