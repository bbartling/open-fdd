import BuildingCheckEngine from "../components/BuildingCheckEngine";
import HomeBuildingInsight from "../components/HomeBuildingInsight";

export default function HomePage() {
  return (
    <div className="home-check-engine">
      <BuildingCheckEngine />
      <HomeBuildingInsight />
    </div>
  );
}
