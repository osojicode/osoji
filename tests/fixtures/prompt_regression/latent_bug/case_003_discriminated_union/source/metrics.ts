interface FileNode {
  type: "file";
  name: string;
  size: number;
  extension: string;
}

interface DirectoryNode {
  type: "directory";
  name: string;
  children: FsNode[];
}

type FsNode = FileNode | DirectoryNode;

export function getNodeLabel(node: FsNode): string {
  if (node.type === "directory") {
    return `${node.name}/ (${node.children.length} items)`;
  }
  // After the discriminant check above, node is narrowed to FileNode
  return `${node.name} (${node.size} bytes, .${node.extension})`;
}

export function collectFiles(node: FsNode): FileNode[] {
  if (node.type === "file") {
    return [node];
  }
  // node is narrowed to DirectoryNode here
  return node.children.flatMap(collectFiles);
}
