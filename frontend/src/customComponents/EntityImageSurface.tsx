import { useRef, useState } from "react";
import { Menu, MenuItem } from "@mui/material";
import type { MediaAsset } from "../types";

export function EntityImageSurface({
  asset,
  alt,
  className = "",
  placeholder,
  onGenerate,
  onGenerateWithPrompt,
  onRegenerate,
  onRegenerateWithPrompt,
  onDelete,
  onUpload,
}: {
  asset?: MediaAsset | null;
  alt: string;
  className?: string;
  placeholder?: string;
  onGenerate?: () => void;
  onGenerateWithPrompt?: () => void;
  onRegenerate?: (asset: MediaAsset) => void;
  onRegenerateWithPrompt?: (asset: MediaAsset) => void;
  onDelete?: (asset: MediaAsset) => void;
  onUpload?: (file: File) => void;
}) {
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const open = Boolean(anchor);
  const hasImage = Boolean(asset?.file_path);

  return <>
    <button
      type="button"
      className={`entity-image-surface ${className}`}
      aria-label={`${alt} image actions`}
      onClick={event => setAnchor(event.currentTarget)}
    >
      {asset?.file_path
        ? <img src={`/media/${asset.file_path}`} alt={alt} />
        : <span className="entity-image-placeholder">{placeholder ?? asset?.kind ?? "image"}</span>}
    </button>
    <Menu
      anchorEl={anchor}
      open={open}
      onClose={() => setAnchor(null)}
      anchorOrigin={{ vertical: "bottom", horizontal: "left" }}
    >
      {!hasImage && onGenerate && <MenuItem onClick={() => { setAnchor(null); onGenerate(); }}>Generate</MenuItem>}
      {!hasImage && onGenerateWithPrompt && <MenuItem onClick={() => { setAnchor(null); onGenerateWithPrompt(); }}>Generate with custom prompt</MenuItem>}
      {hasImage && asset && onRegenerate && <MenuItem onClick={() => { setAnchor(null); onRegenerate(asset); }}>Regenerate</MenuItem>}
      {hasImage && asset && onRegenerateWithPrompt && <MenuItem onClick={() => { setAnchor(null); onRegenerateWithPrompt(asset); }}>Regenerate with custom prompt</MenuItem>}
      {onUpload && <MenuItem onClick={() => { setAnchor(null); inputRef.current?.click(); }}>{hasImage ? "Replace with uploaded image" : "Upload image"}</MenuItem>}
      {hasImage && asset && onDelete && <MenuItem onClick={() => { setAnchor(null); onDelete(asset); }}>Delete image</MenuItem>}
    </Menu>
    {onUpload && <input
      ref={inputRef}
      hidden
      type="file"
      accept="image/png,image/jpeg,image/webp"
      onChange={event => {
        const file = event.target.files?.[0];
        if (file) onUpload(file);
        event.currentTarget.value = "";
      }}
    />}
  </>;
}
