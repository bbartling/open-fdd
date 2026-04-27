type Props = {
  title: string;
  description: string;
};

export function PlaceholderPage({ title, description }: Props) {
  return (
    <div className="card">
      <h2 className="title">{title}</h2>
      <p>{description}</p>
    </div>
  );
}
