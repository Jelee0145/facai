"use client";

import React from "react";

interface ImageGalleryProps {
  images: string[];
  proxyImg: (url: string) => string;
  onImageClick: (url: string) => void;
}

export const ImageGallery = React.memo(function ImageGallery({
  images,
  proxyImg,
  onImageClick,
}: ImageGalleryProps) {
  if (images.length === 0) return null;
  return (
    <div className="mt-8">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-bold text-white">生成结果</h3>
        <span className="text-white/50 text-sm">{images.length} 张</span>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
        {images.map((imgUrl, index) => (
          <div
            key={index}
            className="relative group cursor-pointer rounded-xl overflow-hidden bg-white/5"
            onClick={() => onImageClick(imgUrl)}
          >
            <img
              src={proxyImg(imgUrl)}
              alt={`生成图 ${index + 1}`}
              className="w-full aspect-[3/4] object-cover"
              loading="lazy"
              decoding="async"
            />
          </div>
        ))}
      </div>
    </div>
  );
});
