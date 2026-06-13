import { useState, useEffect, lazy, Suspense } from "react";
import useForestScene from "./hooks/useForestScene";
import useForestData from "./hooks/useForestData";
import usePointerMutation from "./hooks/usePointerMutation";
import useQueryPathLogger from "./hooks/useQueryPathLogger";
import useAuth from "./hooks/useAuth";

const DemoApp = lazy(() => import("./demo/DemoApp"));
const ExplainerPage = lazy(() => import("./explainer/ExplainerPage"));
import Legend from "./components/Legend";
import InstanceBrowser from "./components/InstanceBrowser";
import InfoPanel from "./components/InfoPanel";
import HousePanel from "./components/HousePanel";
import ProjectionDemo from "./components/ProjectionDemo";
import TablePanel from "./components/TablePanel";
import InsertPanel from "./components/InsertPanel";
import DuplicatePanel from "./components/DuplicatePanel";
import SearchPanel from "./components/SearchPanel";
import StructureEvolutionAlert from "./components/StructureEvolutionAlert";
import StatsPanel from "./components/StatsPanel";
import ChatPanel from "./components/ChatPanel";
import ClearanceBar from "./components/ClearanceBar";
import "./App.css";

const toolbarBtnStyle = {
  background: "#fff",
  border: "1px solid #ccc",
  padding: "6px 12px",
  fontFamily: "inherit",
  fontSize: 11,
  cursor: "pointer",
  letterSpacing: "0.02em",
};

const viewFallback = (
  <div style={{ width: "100vw", height: "100vh", display: "flex", alignItems: "center", justifyContent: "center", fontFamily: "inherit" }}>
    Loading...
  </div>
);

export default function App() {
  const [view, setView] = useState("story"); // "story" | "forest" | "demo"

  if (view === "story") {
    return (
      <Suspense fallback={viewFallback}>
        <ExplainerPage
          onEnterForest={() => setView("forest")}
          onRunDemo={() => setView("demo")}
        />
      </Suspense>
    );
  }

  if (view === "demo") {
    return (
      <Suspense fallback={viewFallback}>
        <DemoApp onExit={() => setView("story")} />
      </Suspense>
    );
  }

  return <MainApp onDemo={() => setView("demo")} onStory={() => setView("story")} />;
}

function MainApp({ onDemo, onStory }) {
  const { trees, branchIndex, houses, refetch } = useForestData();
  const {
    insertPointer, resolveDuplicate,
    isSubmitting, lastResult, error,
    clearResult, clearError,
  } = usePointerMutation();

  const { logPointerAccess } = useQueryPathLogger();
  const { identity, loading: authLoading, signInAsPartner, signOutToAnalyst } = useAuth();

  const [showInsert, setShowInsert] = useState(false);
  const [showSearch, setShowSearch] = useState(false);
  const [showStats, setShowStats] = useState(false);
  const [showChat, setShowChat] = useState(false);
  const [dupeResult, setDupeResult] = useState(null);

  const {
    canvasRef,
    hovered,
    setHovered,
    info,
    setInfo,
    autoRotate,
    setAutoRotate,
    selected,
    inboundLinks,
    focusedTree,
    exitFocusMode,
    selectedHouse,
    setSelectedHouse,
    selectedDb,
    setSelectedDb,
  } = useForestScene({ trees, branchIndex, houses });

  // Log pointer access whenever info (selected pointer) changes
  useEffect(() => {
    if (info) logPointerAccess(info);
  }, [info, logPointerAccess]);

  const handleInsert = async (data) => {
    const result = await insertPointer(data);
    if (result?.status === "created") {
      refetch();
    } else if (result?.status === "pending_review") {
      setDupeResult(result);
    } else if (result?.status === "merged") {
      // Auto-merged, refresh to update any metadata
      refetch();
    }
  };

  const handleResolveDuplicate = async (flagId, resolution) => {
    await resolveDuplicate(flagId, resolution);
    setDupeResult(null);
    clearResult();
    refetch();
  };

  return (
    <div className="forest-root">
      <canvas ref={canvasRef} style={{ display: "block", width: "100%", height: "100%" }} />

      {!focusedTree && (
        <>
          <ClearanceBar
            identity={identity}
            loading={authLoading}
            onSignInPartner={signInAsPartner}
            onSignOutAnalyst={signOutToAnalyst}
          />

          <Legend
            autoRotate={autoRotate}
            onToggleAutoRotate={() => setAutoRotate((v) => !v)}
          />

          <InstanceBrowser
            info={info}
            hovered={hovered}
            onSelect={setInfo}
            onHover={setHovered}
            trees={trees}
          />
        </>
      )}

      <InfoPanel
        selected={selected}
        inboundLinks={inboundLinks}
        onSelect={setInfo}
        onClose={() => setInfo(null)}
        branchIndex={branchIndex}
      />

      <HousePanel
        houseId={selectedHouse}
        onClose={() => setSelectedHouse(null)}
      />

      <TablePanel
        open={selectedDb}
        onClose={() => setSelectedDb(null)}
        onSelectHouse={(houseId) => {
          setSelectedDb(null);
          setSelectedHouse(houseId);
        }}
      />

      {focusedTree && (
        <button
          onClick={() => {
            setInfo(null);
            exitFocusMode();
          }}
          className="panel"
          style={{
            top: 24,
            right: 24,
            background: "#111",
            color: "#fff",
            border: "1px solid #333",
            padding: "8px 18px",
            fontFamily: "inherit",
            fontSize: 13,
            cursor: "pointer",
            letterSpacing: "0.02em",
          }}
        >
          Back to forest
        </button>
      )}

      {/* Toolbar */}
      {!focusedTree && (
        <div
          className="panel"
          style={{
            bottom: 24,
            left: "50%",
            transform: "translateX(-50%)",
            display: "flex",
            gap: 6,
          }}
        >
          <button
            onClick={() => { setShowInsert(!showInsert); setShowSearch(false); setShowStats(false); setShowChat(false); }}
            style={{
              ...toolbarBtnStyle,
              background: showInsert ? "#111" : "#fff",
              color: showInsert ? "#fff" : "#333",
            }}
          >
            + Insert
          </button>
          <button
            onClick={() => { setShowSearch(!showSearch); setShowInsert(false); setShowStats(false); setShowChat(false); }}
            style={{
              ...toolbarBtnStyle,
              background: showSearch ? "#111" : "#fff",
              color: showSearch ? "#fff" : "#333",
            }}
          >
            Search
          </button>
          <button
            onClick={() => { setShowStats(!showStats); setShowInsert(false); setShowSearch(false); setShowChat(false); }}
            style={{
              ...toolbarBtnStyle,
              background: showStats ? "#111" : "#fff",
              color: showStats ? "#fff" : "#333",
            }}
          >
            Stats
          </button>
          <button
            onClick={() => { setShowChat(!showChat); setShowInsert(false); setShowSearch(false); setShowStats(false); }}
            style={{
              ...toolbarBtnStyle,
              background: showChat ? "#111" : "#fff",
              color: showChat ? "#fff" : "#333",
            }}
          >
            Chat
          </button>
          <button
            onClick={onDemo}
            style={{
              ...toolbarBtnStyle,
              background: "#1a1a2e",
              color: "#fff",
              border: "1px solid #333",
            }}
          >
            Demo
          </button>
          <button onClick={onStory} style={toolbarBtnStyle}>
            How it works
          </button>
        </div>
      )}

      {/* Insert Panel */}
      <InsertPanel
        open={showInsert}
        onClose={() => { setShowInsert(false); clearResult(); clearError(); }}
        onInsert={handleInsert}
        isSubmitting={isSubmitting}
        lastResult={lastResult}
        error={error}
        onClearResult={clearResult}
        onShowDuplicates={(result) => setDupeResult(result)}
      />

      {/* Search Panel */}
      <SearchPanel
        open={showSearch}
        onClose={() => setShowSearch(false)}
        onSelect={(pointerId) => {
          setInfo(pointerId);
          setShowSearch(false);
        }}
      />

      {/* Duplicate Resolution Panel (modal overlay) */}
      <DuplicatePanel
        insertResult={dupeResult}
        onResolve={handleResolveDuplicate}
        onClose={() => { setDupeResult(null); clearResult(); }}
      />

      {/* Stats Panel */}
      <StatsPanel open={showStats} onClose={() => setShowStats(false)} />

      {/* Chat Panel */}
      <ChatPanel
        open={showChat}
        onClose={() => setShowChat(false)}
        onSelect={(pointerId) => {
          setInfo(pointerId);
        }}
      />

      {/* Structure evolution notification */}
      <StructureEvolutionAlert onRefresh={refetch} />

      <ProjectionDemo />
    </div>
  );
}
