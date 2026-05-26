"use client";

import React from "react";

interface Model {
  code: string;
  name: string;
  icon: string;
  desc: string;
}

interface ModelPickerProps {
  models: Model[];
  selected: string;
  onSelect: (code: string) => void;
}

export const ModelPicker = React.memo(function ModelPicker({
  models,
  selected,
  onSelect,
}: ModelPickerProps) {
  return (
    <section className="mb-8">
      <h2 className="text-xl font-bold text-white mb-4 flex items-center gap-2">
        <span>🤖</span> 选择AI模型
      </h2>
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
        {models.map((model) => (
          <button
            key={model.code}
            onClick={() => onSelect(model.code)}
            className={`p-4 rounded-xl transition-all ${
              selected === model.code
                ? "bg-gradient-to-br from-blue-500 to-cyan-500 text-white shadow-lg shadow-blue-500/30 scale-105"
                : "bg-white/10 text-white/80 hover:bg-white/20"
            }`}
          >
            <div className="text-3xl mb-2">{model.icon}</div>
            <div className="text-sm font-bold">{model.name}</div>
            <div className="text-xs opacity-70 mt-1">{model.desc}</div>
          </button>
        ))}
      </div>
    </section>
  );
});
