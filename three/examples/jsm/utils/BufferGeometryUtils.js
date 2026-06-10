// BufferGeometryUtils.js — minimal stub for Three.js r170
// Only toTrianglesDrawMode is required by GLTFLoader

import {
    TrianglesDrawMode,
    TriangleStripDrawMode,
    TriangleFanDrawMode,
} from 'three';

function toTrianglesDrawMode( geometry, drawMode ) {

    if ( drawMode === TrianglesDrawMode ) return geometry;

    if ( drawMode === TriangleStripDrawMode || drawMode === TriangleFanDrawMode ) {

        let index = geometry.getIndex();

        if ( index === null ) {
            const indices = [];
            const position = geometry.getAttribute( 'position' );
            if ( position !== undefined ) {
                for ( let i = 0; i < position.count; i ++ ) indices.push( i );
                geometry.setIndex( indices );
                index = geometry.getIndex();
            } else {
                console.error( 'toTrianglesDrawMode(): Undefined position attribute.' );
                return geometry;
            }
        }

        const numberOfTriangles = index.count - 2;
        const newIndices = [];

        if ( drawMode === TriangleStripDrawMode ) {
            for ( let i = 0; i < numberOfTriangles; i ++ ) {
                if ( i % 2 === 0 ) {
                    newIndices.push( index.getX( i ), index.getX( i + 1 ), index.getX( i + 2 ) );
                } else {
                    newIndices.push( index.getX( i + 2 ), index.getX( i + 1 ), index.getX( i ) );
                }
            }
        } else {
            for ( let i = 1; i <= numberOfTriangles; i ++ ) {
                newIndices.push( index.getX( 0 ), index.getX( i ), index.getX( i + 1 ) );
            }
        }

        const newGeometry = geometry.clone();
        newGeometry.setIndex( newIndices );
        newGeometry.clearGroups();
        return newGeometry;

    }

    console.error( 'toTrianglesDrawMode(): Unknown draw mode:', drawMode );
    return geometry;

}

export { toTrianglesDrawMode };
