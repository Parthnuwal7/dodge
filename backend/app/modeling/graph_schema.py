from collections import deque

from pydantic import BaseModel


class NodeSchema(BaseModel):
    label: str                            # PascalCase Neo4j label
    source_entity: str | None = None      # folder name, e.g. "sales_order_headers"
    properties: dict[str, str]            # column_name -> pandas dtype string
    id_field: str | list[str]             # primary identifier column(s) — list for composite keys

    @property
    def id_fields(self) -> list[str]:
        """Always return id_field as a list."""
        if isinstance(self.id_field, list):
            return self.id_field
        return [self.id_field]


class EdgeSchema(BaseModel):
    type: str                             # UPPER_SNAKE relationship type
    from_node: str                        # source node label
    to_node: str                          # target node label
    join_on: tuple[str, str]              # (source_field, target_field)
    source_entity: str | None = None      # bridge table folder name (reads data from this DF)
    rel_properties: list[str] | None = None   # columns to copy as relationship properties
    bridge_target_field: str | None = None    # bridge column for target match (when != target id)


class GraphSchema(BaseModel):
    nodes: list[NodeSchema]
    edges: list[EdgeSchema]

    def get_node(self, label: str) -> NodeSchema | None:
        for n in self.nodes:
            if n.label == label:
                return n
        return None

    def node_labels(self) -> list[str]:
        return [n.label for n in self.nodes]

    def edge_types(self) -> list[str]:
        return [e.type for e in self.edges]

    def edge_descriptions(self) -> list[str]:
        """Return edges as 'FromNode -[TYPE]-> ToNode' strings, with rel props if present."""
        descs: list[str] = []
        for e in self.edges:
            desc = f"{e.from_node} -[{e.type}]-> {e.to_node}"
            if e.rel_properties:
                desc += f" {{{', '.join(e.rel_properties)}}}"
            descs.append(desc)
        return descs

    def node_properties_summary(self, max_properties_per_node: int | None = None) -> list[str]:
        """Return per-node property summaries for LLM context."""
        lines = []
        for n in self.nodes:
            id_str = ", ".join(n.id_fields) if isinstance(n.id_field, list) else n.id_field
            props = [p for p in n.properties.keys() if p not in n.id_fields]
            if max_properties_per_node is not None and len(props) > max_properties_per_node:
                props = props[:max_properties_per_node] + ["..."]
            lines.append(f"{n.label} (PRIMARY KEY: `{id_str}`): {', '.join(props)}")
        return lines

    def extract_relevant_subschema(self, seed_labels: list[str]) -> "GraphSchema":
        """Extract a relevant schema slice using BFS pathfinding between seed labels."""
        existing_labels = set(self.node_labels())
        seeds = [label for label in dict.fromkeys(seed_labels) if label in existing_labels]
        if not seeds:
            return self

        selected_nodes = set(seeds)
        selected_edges: set[int] = set()

        if len(seeds) == 1:
            self._add_two_hop_edges(seeds[0], selected_nodes, selected_edges)
            return self._build_subschema(selected_nodes, selected_edges)

        found_path = False
        for i, start in enumerate(seeds):
            for end in seeds[i + 1:]:
                path_edges = self._shortest_path_edges(start, end)
                if not path_edges:
                    continue
                found_path = True
                for edge_idx in path_edges:
                    edge = self.edges[edge_idx]
                    selected_edges.add(edge_idx)
                    selected_nodes.add(edge.from_node)
                    selected_nodes.add(edge.to_node)

        if not found_path:
            for seed in seeds:
                self._add_incident_edges(seed, selected_nodes, selected_edges)

        return self._build_subschema(selected_nodes, selected_edges)

    def _shortest_path_edges(self, start: str, end: str) -> list[int]:
        adjacency: dict[str, list[tuple[str, int]]] = {}
        for idx, edge in enumerate(self.edges):
            adjacency.setdefault(edge.from_node, []).append((edge.to_node, idx))
            adjacency.setdefault(edge.to_node, []).append((edge.from_node, idx))

        queue = deque([start])
        parents: dict[str, tuple[str, int] | None] = {start: None}

        while queue:
            current = queue.popleft()
            if current == end:
                break
            for neighbor, edge_idx in adjacency.get(current, []):
                if neighbor in parents:
                    continue
                parents[neighbor] = (current, edge_idx)
                queue.append(neighbor)

        if end not in parents:
            return []

        path_edges: list[int] = []
        cursor = end
        while parents[cursor] is not None:
            parent, edge_idx = parents[cursor]
            path_edges.append(edge_idx)
            cursor = parent
        path_edges.reverse()
        return path_edges

    def _add_incident_edges(
        self,
        label: str,
        selected_nodes: set[str],
        selected_edges: set[int],
    ) -> None:
        for idx, edge in enumerate(self.edges):
            if edge.from_node == label or edge.to_node == label:
                selected_edges.add(idx)
                selected_nodes.add(edge.from_node)
                selected_nodes.add(edge.to_node)

    def _add_two_hop_edges(
        self,
        label: str,
        selected_nodes: set[str],
        selected_edges: set[int],
    ) -> None:
        """Include incident edges for seed node and its immediate neighbors."""
        self._add_incident_edges(label, selected_nodes, selected_edges)
        neighbors = {n for n in selected_nodes if n != label}
        for neighbor in neighbors:
            self._add_incident_edges(neighbor, selected_nodes, selected_edges)

    def _build_subschema(self, selected_nodes: set[str], selected_edges: set[int]) -> "GraphSchema":
        nodes = [node for node in self.nodes if node.label in selected_nodes]
        edges = [edge for idx, edge in enumerate(self.edges) if idx in selected_edges]
        return GraphSchema(nodes=nodes, edges=edges)

    def find_candidate_path_patterns(self, seed_labels: list[str]) -> list[str]:
        """Find candidate traversal patterns between seed labels using BFS shortest paths."""
        existing_labels = set(self.node_labels())
        seeds = [label for label in dict.fromkeys(seed_labels) if label in existing_labels]
        if not seeds:
            return []

        patterns: list[str] = []
        if len(seeds) == 1:
            return self._two_hop_path_patterns(seeds[0])

        for i, start in enumerate(seeds):
            for end in seeds[i + 1:]:
                steps = self._shortest_path_steps(start, end)
                if not steps:
                    continue
                patterns.append(self._steps_to_pattern(start, steps))

        if patterns:
            return list(dict.fromkeys(patterns))

        for seed in seeds:
            patterns.extend(self._incident_path_patterns(seed))
        return list(dict.fromkeys(patterns))

    def _shortest_path_steps(self, start: str, end: str) -> list[tuple[str, bool, str]]:
        """Return shortest path as (relationship_type, forward_direction, next_label) steps."""
        adjacency: dict[str, list[tuple[str, int]]] = {}
        for idx, edge in enumerate(self.edges):
            adjacency.setdefault(edge.from_node, []).append((edge.to_node, idx))
            adjacency.setdefault(edge.to_node, []).append((edge.from_node, idx))

        queue = deque([start])
        parents: dict[str, tuple[str, int] | None] = {start: None}

        while queue:
            current = queue.popleft()
            if current == end:
                break
            for neighbor, edge_idx in adjacency.get(current, []):
                if neighbor in parents:
                    continue
                parents[neighbor] = (current, edge_idx)
                queue.append(neighbor)

        if end not in parents:
            return []

        node_path: list[str] = [end]
        edge_path: list[int] = []
        cursor = end
        while parents[cursor] is not None:
            parent, edge_idx = parents[cursor]
            edge_path.append(edge_idx)
            node_path.append(parent)
            cursor = parent
        node_path.reverse()
        edge_path.reverse()

        steps: list[tuple[str, bool, str]] = []
        for i, edge_idx in enumerate(edge_path):
            edge = self.edges[edge_idx]
            current_label = node_path[i]
            next_label = node_path[i + 1]
            is_forward = edge.from_node == current_label and edge.to_node == next_label
            steps.append((edge.type, is_forward, next_label))
        return steps

    @staticmethod
    def _steps_to_pattern(start_label: str, steps: list[tuple[str, bool, str]]) -> str:
        pattern = f"(:`{start_label}`)"
        for rel_type, is_forward, next_label in steps:
            if is_forward:
                pattern += f"-[:{rel_type}]->(:`{next_label}`)"
            else:
                pattern += f"<-[:{rel_type}]-(:`{next_label}`)"
        return pattern

    def _incident_path_patterns(self, label: str) -> list[str]:
        patterns: list[str] = []
        for edge in self.edges:
            if edge.from_node == label:
                patterns.append(f"(:`{label}`)-[:{edge.type}]->(:`{edge.to_node}`)")
            elif edge.to_node == label:
                patterns.append(f"(:`{label}`)<-[:{edge.type}]-(:`{edge.from_node}`)")
        return patterns

    def _two_hop_path_patterns(self, label: str) -> list[str]:
        """Build 1-hop and 2-hop directional candidate patterns from a single seed."""
        one_hop = self._incident_path_patterns(label)
        patterns: list[str] = list(one_hop)

        for idx, edge in enumerate(self.edges):
            if edge.from_node == label:
                neighbor = edge.to_node
                first = f"(:`{label}`)-[:{edge.type}]->(:`{neighbor}`)"
            elif edge.to_node == label:
                neighbor = edge.from_node
                first = f"(:`{label}`)<-[:{edge.type}]-(:`{neighbor}`)"
            else:
                continue

            for j, second_edge in enumerate(self.edges):
                if j == idx:
                    continue
                if second_edge.from_node == neighbor:
                    second = f"-[:{second_edge.type}]->(:`{second_edge.to_node}`)"
                elif second_edge.to_node == neighbor:
                    second = f"<-[:{second_edge.type}]-(:`{second_edge.from_node}`)"
                else:
                    continue
                patterns.append(first + second)

        return list(dict.fromkeys(patterns))
