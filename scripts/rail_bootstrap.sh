#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$project_dir/rail-routing/versions.env"

work_dir="${RAIL_WORK_DIR:-$project_dir/data/rail-routing}"
tools_dir="$work_dir/tools"
upstream_dir="$work_dir/upstream/OpenRailRouting"
graphhopper_dir="$work_dir/upstream/GraphHopper"
build_root="$work_dir/build"
dist_dir="$work_dir/dist"
maven_dir="$tools_dir/apache-maven-$MAVEN_VERSION"
maven_archive="$tools_dir/apache-maven-$MAVEN_VERSION-bin.tar.gz"
jar_name="railway_routing-$OPENRAILROUTING_ARTIFACT_VERSION.jar"

if [[ -n "${RAIL_JAVA_HOME:-}" ]]; then
  if [[ ! -x "$RAIL_JAVA_HOME/bin/java" ]]; then
    echo "RAIL_JAVA_HOME does not contain an executable bin/java: $RAIL_JAVA_HOME" >&2
    exit 2
  fi
  export JAVA_HOME="$RAIL_JAVA_HOME"
  java_bin="$JAVA_HOME/bin/java"
  jar_bin="$JAVA_HOME/bin/jar"
else
  java_bin="$(command -v java)"
  jar_bin="$(command -v jar)"
fi

java_version="$("$java_bin" -XshowSettings:properties -version 2>&1 | awk -F'= ' '/java.specification.version/ {print $2; exit}')"
java_major="${java_version%%.*}"
if [[ -z "$java_major" || "$java_major" -lt 17 ]]; then
  echo "OpenRailRouting requires Java 17 or newer; found '${java_version:-unknown}'." >&2
  exit 2
fi

mkdir -p "$tools_dir" "$work_dir/upstream" "$build_root" "$dist_dir"

if [[ ! -x "$maven_dir/bin/mvn" ]]; then
  if [[ ! -f "$maven_archive" ]]; then
    curl --fail --location --retry 3 --output "$maven_archive" "$MAVEN_ARCHIVE_URL"
  fi
  actual_sha="$(shasum -a 512 "$maven_archive" | awk '{print $1}')"
  if [[ "$actual_sha" != "$MAVEN_ARCHIVE_SHA512" ]]; then
    echo "Maven archive SHA-512 mismatch." >&2
    exit 3
  fi
  tar -xzf "$maven_archive" -C "$tools_dir"
fi

if [[ ! -d "$upstream_dir/.git" ]]; then
  mkdir -p "$upstream_dir"
  git -C "$upstream_dir" init
  git -C "$upstream_dir" remote add origin "$OPENRAILROUTING_REPOSITORY"
fi

if [[ ! -d "$graphhopper_dir/.git" ]]; then
  mkdir -p "$graphhopper_dir"
  git -C "$graphhopper_dir" init
  git -C "$graphhopper_dir" remote add origin "$GRAPHHOPPER_REPOSITORY"
fi

if ! git -C "$upstream_dir" diff --quiet || ! git -C "$upstream_dir" diff --cached --quiet; then
  echo "Refusing to replace a modified OpenRailRouting checkout: $upstream_dir" >&2
  exit 4
fi
if ! git -C "$graphhopper_dir" diff --quiet || ! git -C "$graphhopper_dir" diff --cached --quiet; then
  echo "Refusing to replace a modified GraphHopper checkout: $graphhopper_dir" >&2
  exit 4
fi

git -C "$upstream_dir" fetch --depth 1 origin "$OPENRAILROUTING_COMMIT"
git -C "$upstream_dir" checkout --detach FETCH_HEAD
git -C "$graphhopper_dir" fetch --depth 1 origin "$GRAPHHOPPER_COMMIT"
git -C "$graphhopper_dir" checkout --detach FETCH_HEAD

"$maven_dir/bin/mvn" --batch-mode -f "$graphhopper_dir/pom.xml" \
  -DskipTests -pl core,web-api,map-matching,web-bundle,web -am install

openrail_build_dir="$(mktemp -d "$build_root/OpenRailRouting.XXXXXX")"
cleanup() {
  if [[ -n "${openrail_build_dir:-}" && -d "$openrail_build_dir" ]]; then
    rm -rf "$openrail_build_dir"
  fi
}
trap cleanup EXIT INT TERM
git -C "$upstream_dir" archive "$OPENRAILROUTING_COMMIT" | tar -x -C "$openrail_build_dir"
patch -p1 -d "$openrail_build_dir" \
  < "$project_dir/rail-routing/patches/0001-metro2fog-metadata-endpoint.patch"
patch -p1 -d "$openrail_build_dir" \
  < "$project_dir/rail-routing/patches/0002-transit2fog-metadata-endpoint.patch"
"$maven_dir/bin/mvn" --batch-mode -f "$openrail_build_dir/pom.xml" clean package
cp "$openrail_build_dir/target/$jar_name" "$dist_dir/openrailrouting.jar"

if ! "$jar_bin" tf "$dist_dir/openrailrouting.jar" \
  | grep -q '^de/geofabrik/railway_routing/http/Metro2FogMetadataResource.class$'; then
  echo "Built JAR is missing the legacy Metro2Fog metadata resource." >&2
  exit 5
fi
if ! "$jar_bin" tf "$dist_dir/openrailrouting.jar" \
  | grep -q '^de/geofabrik/railway_routing/http/Transit2FogMetadataResource.class$'; then
  echo "Built JAR is missing the Transit2GPX metadata resource." >&2
  exit 5
fi

echo "OpenRailRouting $OPENRAILROUTING_COMMIT built at $dist_dir/openrailrouting.jar"
