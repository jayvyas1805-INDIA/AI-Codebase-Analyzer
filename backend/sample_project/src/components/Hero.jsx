import React from "react";
import clsx from "clsx";
import "./Hero.css";

export default function Hero({ isActive, isHighlighted, theme }) {
  return (
    <div
      className={clsx("container", "hero", isActive && "active", {
        highlighted: isHighlighted,
      })}
    >
      <p className="unused-in-css">This class has no CSS definition.</p>
      <span className={`badge ${theme}`}>Badge</span>
      <button className={isActive ? "btn-active" : "btn-inactive"}>Click</button>
    </div>
  );
}
