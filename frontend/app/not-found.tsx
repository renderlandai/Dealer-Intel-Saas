import Link from "next/link";
import { FileQuestion } from "lucide-react";

export default function NotFound() {
  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center gap-6 px-4">
      <div className="flex h-16 w-16 items-center justify-center rounded-full bg-zinc-800">
        <FileQuestion className="h-8 w-8 text-zinc-400" />
      </div>
      <div className="text-center">
        <h2 className="text-xl font-semibold text-zinc-100">Page not found</h2>
        <p className="mt-2 text-sm text-zinc-400">
          The page you&apos;re looking for doesn&apos;t exist or has been moved.
        </p>
      </div>
      <Link
        href="/"
        className="rounded-lg bg-zinc-800 px-4 py-2 text-sm font-medium text-zinc-100 transition-colors hover:bg-zinc-700"
      >
        Back to Dashboard
      </Link>
    </div>
  );
}
