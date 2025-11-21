import * as React from "react";
import { Loader } from "./components/Loader";

export default function App() {
  return (
    <div className="min-h-screen bg-gradient-to-br from-gray-950 via-gray-900 to-gray-950">
      {/* Hero Section */}
      <div className="flex items-center justify-center min-h-screen p-4">
        <div className="text-center space-y-6 max-w-md">
          <Loader size="lg" />
          <div className="space-y-2">
            <h1 className="text-white text-2xl">Loading your experience</h1>
            <p className="text-gray-400">Please wait while we prepare everything for you</p>
          </div>
        </div>
      </div>
      
      {/* Examples Section */}
      <div className="container mx-auto px-4 pb-24">
        <div className="max-w-4xl mx-auto space-y-12">
          <div className="text-center space-y-4">
            <h2 className="text-gray-300 text-xl">Component Variations</h2>
            <p className="text-gray-500">Use the loader component throughout your application</p>
          </div>
          
          <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
            {/* Small */}
            <div className="bg-gray-900/50 backdrop-blur-sm rounded-2xl p-8 border border-gray-800 flex flex-col items-center gap-4">
              <Loader size="sm" />
              <div className="text-center">
                <p className="text-gray-300">Small</p>
                <p className="text-gray-500 text-sm">Inline usage</p>
              </div>
            </div>
            
            {/* Medium */}
            <div className="bg-gray-900/50 backdrop-blur-sm rounded-2xl p-8 border border-gray-800 flex flex-col items-center gap-4">
              <Loader size="md" />
              <div className="text-center">
                <p className="text-gray-300">Medium</p>
                <p className="text-gray-500 text-sm">Default size</p>
              </div>
            </div>
            
            {/* Large */}
            <div className="bg-gray-900/50 backdrop-blur-sm rounded-2xl p-8 border border-gray-800 flex flex-col items-center gap-4">
              <Loader size="lg" />
              <div className="text-center">
                <p className="text-gray-300">Large</p>
                <p className="text-gray-500 text-sm">Full screen</p>
              </div>
            </div>
          </div>
          
          {/* With Text Examples */}
          <div className="space-y-6">
            <h3 className="text-gray-300 text-center">With Loading Messages</h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <div className="bg-gray-900/50 backdrop-blur-sm rounded-2xl p-8 border border-gray-800 flex items-center justify-center">
                <Loader size="md" text="Processing..." />
              </div>
              <div className="bg-gray-900/50 backdrop-blur-sm rounded-2xl p-8 border border-gray-800 flex items-center justify-center">
                <Loader size="md" text="Uploading files..." />
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
