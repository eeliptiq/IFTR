import React, { useRef, useState } from 'react';
import axios from 'axios';
import { toast } from 'sonner';
import { Button } from './ui/button';
import { Input } from './ui/input';
import { Label } from './ui/label';
import { useAuth } from '../contexts/AuthContext';
import { API_BASE, imageSrc } from '../lib/images';
import { ImagePlus, Link2, Loader2, Upload, X } from 'lucide-react';

const ACCEPTED_TYPES = ['image/jpeg', 'image/png', 'image/gif', 'image/webp'];
const MAX_BYTES = 5 * 1024 * 1024;

/**
 * Image picker with two ways in: upload a file, or paste a URL.
 *
 * Either way the value handed back to the parent is a plain string suitable
 * for the `image_url` field, so callers do not need to know which was used.
 */
const ImageUploadField = ({
  label = 'Image',
  value,
  onChange,
  id = 'image',
  helpText,
  testId,
}) => {
  const { token } = useAuth();
  const [mode, setMode] = useState('upload');
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef(null);

  const uploadFile = async (file) => {
    if (!file || uploading) return;

    if (!ACCEPTED_TYPES.includes(file.type)) {
      toast.error('Please choose a JPEG, PNG, GIF or WEBP image.');
      return;
    }
    if (file.size > MAX_BYTES) {
      toast.error('Images must be 5 MB or smaller.');
      return;
    }

    setUploading(true);
    try {
      const body = new FormData();
      body.append('file', file);
      // Let axios set the multipart Content-Type so the boundary is included.
      const response = await axios.post(`${API_BASE}/uploads`, body, {
        headers: { Authorization: `Bearer ${token}` },
        withCredentials: true,
      });
      onChange(response.data.url);
      toast.success('Image uploaded');
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Upload failed');
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const modeButtonClass = (target) =>
    `flex items-center gap-1.5 px-3 py-1 text-xs font-medium rounded transition-colors ${
      mode === target ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground'
    }`;

  return (
    <div className="space-y-2">
      <Label htmlFor={id}>{label}</Label>

      <div className="flex gap-1 p-1 rounded-md border w-fit" data-testid={`${testId || id}-mode`}>
        <button type="button" onClick={() => setMode('upload')} className={modeButtonClass('upload')}>
          <Upload className="w-3.5 h-3.5" />
          Upload
        </button>
        <button type="button" onClick={() => setMode('link')} className={modeButtonClass('link')}>
          <Link2 className="w-3.5 h-3.5" />
          Paste URL
        </button>
      </div>

      {mode === 'upload' ? (
        <div
          onClick={() => !uploading && fileInputRef.current?.click()}
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            uploadFile(e.dataTransfer.files?.[0]);
          }}
          className={`flex flex-col items-center justify-center gap-1.5 p-4 rounded-lg border border-dashed transition-colors ${
            uploading ? 'opacity-70 cursor-default' : 'cursor-pointer hover:border-primary/60'
          }`}
          data-testid={`${testId || id}-dropzone`}
        >
          {uploading ? (
            <Loader2 className="w-5 h-5 animate-spin text-primary" />
          ) : (
            <ImagePlus className="w-5 h-5 text-muted-foreground" />
          )}
          <p className="text-xs text-muted-foreground text-center">
            {uploading ? 'Uploading…' : 'Click or drop an image (JPEG, PNG, GIF, WEBP · max 5 MB)'}
          </p>
          <input
            ref={fileInputRef}
            id={id}
            type="file"
            accept={ACCEPTED_TYPES.join(',')}
            className="hidden"
            disabled={uploading}
            onChange={(e) => uploadFile(e.target.files?.[0])}
            data-testid={`${testId || id}-file-input`}
          />
        </div>
      ) : (
        <Input
          id={id}
          value={value || ''}
          onChange={(e) => onChange(e.target.value)}
          placeholder="https://..."
          data-testid={`${testId || id}-url-input`}
        />
      )}

      {helpText && <p className="text-xs text-muted-foreground">{helpText}</p>}

      {value && (
        <div className="relative w-fit">
          <img
            src={imageSrc(value)}
            alt="Preview"
            className="w-48 h-32 object-cover rounded-lg border"
            data-testid={`${testId || id}-preview`}
          />
          <Button
            type="button"
            variant="secondary"
            size="icon"
            className="absolute -top-2 -right-2 h-6 w-6 rounded-full"
            onClick={() => onChange('')}
            aria-label="Remove image"
            data-testid={`${testId || id}-remove`}
          >
            <X className="w-3 h-3" />
          </Button>
        </div>
      )}
    </div>
  );
};

export default ImageUploadField;
