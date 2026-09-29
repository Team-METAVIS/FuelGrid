import { Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import { useLive } from "./lib/live";
import Assistant from "./pages/Assistant";
import Audit from "./pages/Audit";
import Decisions from "./pages/Decisions";
import Intelligence from "./pages/Intelligence";
import Network from "./pages/Network";
import Overview from "./pages/Overview";
import Replay from "./pages/Replay";
import Scenarios from "./pages/Scenarios";
import System from "./pages/System";

export default function App() {
  const { state, connected } = useLive();
  return (
    <Layout>
      {!state?.ready ? (
        <div className="grid h-[60vh] place-items-center text-sm text-slate-500">
          {connected ? "Connecting to the fuel simulator…" : "Waiting for the FuelGrid backend…"}
        </div>
      ) : (
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/network" element={<Network />} />
          <Route path="/recommendations" element={<Decisions />} />
          <Route path="/intelligence" element={<Intelligence />} />
          <Route path="/scenarios" element={<Scenarios />} />
          <Route path="/assistant" element={<Assistant />} />
          <Route path="/replay" element={<Replay />} />
          <Route path="/system" element={<System />} />
          <Route path="/audit" element={<Audit />} />
          <Route path="*" element={<Overview />} />
        </Routes>
      )}
    </Layout>
  );
}
