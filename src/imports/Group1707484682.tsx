import * as React from "react";
import { motion } from "motion/react";
import svgPaths from "./svg-ywvgg4repy";

export default function Group() {
  const segmentVariants = {
    animate: (i: number) => ({
      opacity: [0.2, 1, 0.2],
      scale: [0.95, 1.05, 0.95],
      transition: {
        duration: 1.5,
        repeat: Infinity,
        ease: [0.4, 0, 0.2, 1],
        delay: i * 0.15,
      }
    })
  };

  return (
    <div className="opacity-90 relative size-full">
      <svg className="block size-full" fill="none" preserveAspectRatio="none" viewBox="0 0 23 23">
        <g id="Group 1707484681">
          <path d={svgPaths.pf7e6000} fill="url(#paint0_linear_1_20)" id="Vector" />
          <g style={{ transformOrigin: "11.375px 11.375px" }}>
            <motion.path
              d={svgPaths.p28393400}
              fill="var(--fill-0, white)"
              id="Vector_2"
              custom={0}
              variants={segmentVariants}
              animate="animate"
              style={{ transformOrigin: "11.375px 11.375px" }}
            />
          </g>
          <g style={{ transformOrigin: "11.375px 11.375px" }}>
            <motion.path
              d={svgPaths.p233f1500}
              fill="var(--fill-0, white)"
              id="Vector_3"
              custom={1}
              variants={segmentVariants}
              animate="animate"
              style={{ transformOrigin: "11.375px 11.375px" }}
            />
          </g>
          <g style={{ transformOrigin: "11.375px 11.375px" }}>
            <motion.path
              d={svgPaths.p2753c800}
              fill="var(--fill-0, white)"
              id="Vector_4"
              custom={2}
              variants={segmentVariants}
              animate="animate"
              style={{ transformOrigin: "11.375px 11.375px" }}
            />
          </g>
          <g style={{ transformOrigin: "11.375px 11.375px" }}>
            <motion.path
              d={svgPaths.pabac3c0}
              fill="var(--fill-0, white)"
              id="Vector_5"
              custom={3}
              variants={segmentVariants}
              animate="animate"
              style={{ transformOrigin: "11.375px 11.375px" }}
            />
          </g>
          <g style={{ transformOrigin: "11.375px 11.375px" }}>
            <motion.path
              d={svgPaths.p1bf13a00}
              fill="var(--fill-0, white)"
              id="Vector_6"
              custom={4}
              variants={segmentVariants}
              animate="animate"
              style={{ transformOrigin: "11.375px 11.375px" }}
            />
          </g>
        </g>
        <defs>
          <linearGradient gradientUnits="userSpaceOnUse" id="paint0_linear_1_20" x1="0.854461" x2="21.896" y1="0.852622" y2="21.8942">
            <stop stopColor="#D300FF" />
            <stop offset="0.95" stopColor="#FF7131" />
          </linearGradient>
        </defs>
      </svg>
    </div>
  );
}
