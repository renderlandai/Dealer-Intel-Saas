"use client";

import { useEffect, useState } from "react";
import { ImageIcon } from "lucide-react";
import { api } from "@/lib/api";

interface AssetThumbnailProps {
  assetId: string;
  alt?: string;
  className?: string;
  iconSize?: string;
}

const cache = new Map<string, string>();

export function AssetThumbnail({
  assetId,
  alt = "Asset",
  className = "h-full w-full object-cover",
  iconSize = "h-4 w-4",
}: AssetThumbnailProps) {
  const [src, setSrc] = useState<string | null>(cache.get(assetId) ?? null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (cache.has(assetId)) {
      setSrc(cache.get(assetId)!);
      return;
    }

    let cancelled = false;
    api
      .get(`/campaigns/assets/${assetId}/thumbnail`, { responseType: "blob" })
      .then((res) => {
        if (cancelled) return;
        const url = URL.createObjectURL(res.data);
        cache.set(assetId, url);
        setSrc(url);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });

    return () => {
      cancelled = true;
    };
  }, [assetId]);

  if (failed || !src) {
    return (
      <div className="flex h-full w-full items-center justify-center">
        <ImageIcon className={`${iconSize} text-muted-foreground`} />
      </div>
    );
  }

  return <img src={src} alt={alt} className={className} />;
}
