import CodeMirror from "@uiw/react-codemirror";
import { python } from "@codemirror/lang-python";

type Props = {
  value: string;
  onChange: (value: string) => void;
  height?: string;
};

export default function PythonCodeEditor({ value, onChange, height = "220px" }: Props) {
  return (
    <CodeMirror
      value={value}
      height={height}
      extensions={[python()]}
      theme="dark"
      onChange={onChange}
      basicSetup={{ lineNumbers: true, foldGutter: true }}
    />
  );
}
