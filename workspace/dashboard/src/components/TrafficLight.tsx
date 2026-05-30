type Traffic = "green" | "yellow" | "red";

const ORDER: Traffic[] = ["red", "yellow", "green"];

const LABELS: Record<Traffic, string> = {
  green: "All clear",
  yellow: "Needs attention",
  red: "Action required",
};

export default function TrafficLight({
  traffic,
  size = "md",
}: {
  traffic: Traffic;
  size?: "sm" | "md";
}) {
  return (
    <div className={`traffic-light traffic-${size}`} role="img" aria-label={`Building status: ${LABELS[traffic]}`}>
      <div className="traffic-housing">
        {ORDER.map((lamp) => (
          <span
            key={lamp}
            className={`traffic-lamp lamp-${lamp}${traffic === lamp ? " lit" : ""}`}
          />
        ))}
      </div>
    </div>
  );
}

export type { Traffic };
