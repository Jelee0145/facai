"use client";

import React from "react";

interface Country {
  code: string;
  name: string;
  flag: string;
  currency: string;
  shopUrl: string;
  platform: string;
}

interface CountryPickerProps {
  countries: Country[];
  selected: string;
  onSelect: (code: string) => void;
}

export const CountryPicker = React.memo(function CountryPicker({
  countries,
  selected,
  onSelect,
}: CountryPickerProps) {
  return (
    <section className="mb-8">
      <h2 className="text-xl font-bold text-white mb-4 flex items-center gap-2">
        <span>🌏</span> 选择目标市场
      </h2>
      <div className="grid grid-cols-3 md:grid-cols-5 lg:grid-cols-9 gap-3">
        {countries.map((country) => (
          <button
            key={country.code}
            onClick={() => onSelect(country.code)}
            className={`p-4 rounded-xl transition-all ${
              selected === country.code
                ? "bg-gradient-to-br from-purple-500 to-pink-500 text-white shadow-lg shadow-purple-500/30 scale-105"
                : "bg-white/10 text-white/80 hover:bg-white/20"
            }`}
          >
            <div className="text-2xl mb-1">{country.flag}</div>
            <div className="text-sm font-medium">{country.name}</div>
            <div className="text-xs opacity-70">{country.currency}</div>
          </button>
        ))}
      </div>
    </section>
  );
});
