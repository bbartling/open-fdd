import { useState } from "react";
import BuildingCheckEngine from "../components/BuildingCheckEngine";
import HomeOllamaChat, { HomeOllamaToggle, homeOllamaEnabled } from "../components/HomeOllamaChat";

export default function HomePage() {
  const [ollamaOn, setOllamaOn] = useState(homeOllamaEnabled);

  return (
    <div className="home-check-engine">
      <div className="home-toolbar">
        <HomeOllamaToggle enabled={ollamaOn} onChange={setOllamaOn} />
      </div>
      <BuildingCheckEngine />
      {ollamaOn ? <HomeOllamaChat /> : null}
    </div>
  );
}
