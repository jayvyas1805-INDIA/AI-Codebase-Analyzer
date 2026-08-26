import { useRef, useState } from "react";
import { analyzeProjectZip } from "../api/analysisApi.js";

/**
 * First screen: pick a .zip file and kick off analysis.
 * Calls onAnalyzeStart() before the request, and onAnalyzeComplete(result)
 * or onAnalyzeError(message) when it finishes — App.jsx owns the actual
 * screen-switching logic, this component just reports what happened.
 */
export default function UploadScreen({ onAnalyzeStart, onAnalyzeComplete, onAnalyzeError }) {
  const [selectedFile, setSelectedFile] = useState(null);
  const [isDragging, setIsDragging] = useState(false);
  const fileInputRef = useRef(null);

  function handleFileChosen(file) {
    if (!file) return;
    if (!file.name.endsWith(".zip")) {
      onAnalyzeError("Please select a .zip file.");
      return;
    }
    setSelectedFile(file);
  }

  function handleDrop(e) {
    e.preventDefault();
    setIsDragging(false);
    handleFileChosen(e.dataTransfer.files?.[0]);
  }

  async function handleAnalyzeClick() {
    if (!selectedFile) return;

    onAnalyzeStart();
    try {
      const result = await analyzeProjectZip(selectedFile);
      onAnalyzeComplete(result);
    } catch (err) {
      onAnalyzeError(err.message);
    }
  }

  return (
    <div className="upload-screen">
      <h1>React Codebase Analyzer</h1>
      <p className="subtitle">
        Upload a zipped React project to detect CSS class conflicts, unused
        styles, and undefined classNames.
      </p>

      <div
        className={`drop-zone ${isDragging ? "drop-zone--active" : ""}`}
        onDragOver={(e) => {
          e.preventDefault();
          setIsDragging(true);
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={handleDrop}
        onClick={() => fileInputRef.current?.click()}
      >
        <input
          ref={fileInputRef}
          type="file"
          accept=".zip"
          onChange={(e) => handleFileChosen(e.target.files?.[0])}
          hidden
        />
        {selectedFile ? (
          <p className="drop-zone__file">
            {selectedFile.name} <span>({Math.round(selectedFile.size / 1024)} KB)</span>
          </p>
        ) : (
          <p>Click to choose a .zip file, or drag one here</p>
        )}
      </div>

      <button
        className="analyze-button"
        disabled={!selectedFile}
        onClick={handleAnalyzeClick}
      >
        Analyze Project
      </button>
    </div>
  );
}
